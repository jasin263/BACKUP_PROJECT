from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.http import JsonResponse
from django.urls import reverse
from ..models import ServerConfig, BackupFile, TransferLog, TransferStatus
from ..utils import list_files_on_server, transfer_file, sftp_connect, calculate_folder_size
import os
import logging
from datetime import datetime

logger = logging.getLogger(__name__)

@login_required
def scan_files(request):
    """Scan source server for backup files and folders and register them for transfer"""
    if request.method != 'POST':
        # Only allow POST requests
        return redirect('dashboard')
    
    # Get source server ID from form
    source_server_id = request.POST.get('source_server_id')
    destination_server_id = request.POST.get('destination_server_id')
    
    if not source_server_id or not destination_server_id:
        messages.error(request, 'Source and destination servers are required')
        return redirect('dashboard')
    
    # Get the server objects
    source_server = get_object_or_404(ServerConfig, id=source_server_id, user=request.user, server_type='source')
    destination_server = get_object_or_404(ServerConfig, id=destination_server_id, user=request.user, server_type='destination')
    
    try:
        # List files on source server including folders
        files = list_files_on_server(source_server, include_folders=True)
        
        # Count new files/folders registered
        new_files_count = 0
        
        # Establish SFTP connection to source server for folder size calculation
        ssh, sftp = None, None
        try:
            ssh, sftp = sftp_connect(source_server)
            
            # Register each file/folder for transfer if not already registered
            for file_info in files:
                # Check if file/folder is already registered
                existing = BackupFile.objects.filter(
                    filename=file_info['filename'],
                    source_server=source_server,
                    destination_server=destination_server,
                    user=request.user
                ).first()
                
                if not existing:
                    # Use the configured remote paths for both files and folders
                    source_path = os.path.join(source_server.remote_path, file_info['filename']).replace('\\', '/')
                    destination_path = os.path.join(destination_server.remote_path, file_info['filename']).replace('\\', '/')
                    
                    # Convert line endings of the source file to Linux format if not a folder
                    if not file_info.get('is_folder', False):
                        ssh2, sftp2 = None, None
                        try:
                            from ..utils import convert_remote_file_line_endings_to_linux
                            ssh2, sftp2 = sftp_connect(source_server)
                            convert_remote_file_line_endings_to_linux(sftp2, source_path)
                        except Exception as e:
                            logger.error(f"Failed to convert line endings for {source_path}: {str(e)}")
                        finally:
                            if sftp2:
                                sftp2.close()
                            if ssh2:
                                ssh2.close()
                    
                    # Calculate folder size if folder
                    file_size = file_info.get('size', 0)
                    if file_info.get('is_folder', False):
                        file_size = calculate_folder_size(sftp, source_path)
                        logger.info(f"Calculated folder size for {source_path}: {file_size} bytes")
                    
                    # Register new file or folder for transfer
                    new_file = BackupFile(
                        filename=file_info['filename'],
                        file_size=file_size,
                        file_created_at=file_info.get('created_at'),
                        file_modified_at=file_info.get('modified_at'),
                        source_path=source_path,
                        destination_path=destination_path,
                        status=TransferStatus.PENDING,
                        source_server=source_server,
                        destination_server=destination_server,
                        user=request.user,
                        is_folder=file_info.get('is_folder', False),
                        files_count=0
                    )
                    
                    new_file.save()
                    new_files_count += 1
                    
                    # Log the registration
                    log_entry = TransferLog(
                        backup_file=new_file,
                        action='file_registered',
                        message='File or folder registered for transfer'
                    )
                    log_entry.save()
        finally:
            if sftp:
                sftp.close()
            if ssh:
                ssh.close()
        
        messages.success(request, f'Scan completed! {new_files_count} new files/folders registered for transfer.')
        return redirect('file_list')
        
    except Exception as e:
        messages.error(request, f'Error scanning source server: {str(e)}')
        return redirect('dashboard')


@login_required
def initiate_transfer_all(request):
    """Initiate and process transfer for all pending files and folders in one operation"""
    if request.method != 'POST':
        # Only allow POST requests
        return redirect('file_list')
    
    # Get all pending files and folders
    pending_files = BackupFile.objects.filter(
        user=request.user,
        status=TransferStatus.PENDING
    )
    
    count = pending_files.count()
    
    if count == 0:
        messages.info(request, 'No pending files or folders to transfer')
        return redirect('file_list')
    
    success_count = 0
    failed_count = 0
    
    from concurrent.futures import ThreadPoolExecutor, as_completed
    
    def transfer_and_log(file):
        nonlocal success_count, failed_count
        try:
            file.status = TransferStatus.IN_PROGRESS
            file.save()
            
            init_log = TransferLog(
                backup_file=file,
                action='transfer_initiated',
                message='Batch transfer initiated by user'
            )
            init_log.save()
            
            success, message = transfer_file(file)
            
            if success:
                file.status = TransferStatus.SUCCESS
                log_action = 'transfer_complete'
                success_count += 1
            else:
                file.status = TransferStatus.FAILED
                file.error_message = message
                log_action = 'transfer_failed'
                failed_count += 1
            
            file.save()
            
            result_log = TransferLog(
                backup_file=file,
                action=log_action,
                message=message
            )
            result_log.save()
        except Exception as e:
            failed_count += 1
            file.status = TransferStatus.FAILED
            file.error_message = str(e)
            file.save()
            log = TransferLog(
                backup_file=file,
                action='transfer_failed',
                message=f'Exception during transfer: {str(e)}'
            )
            log.save()
    
    # Retry failed transfers up to 2 times in batch to improve success rate
    max_retries = 2
    for attempt in range(max_retries + 1):
        with ThreadPoolExecutor(max_workers=10) as executor:
            futures = [executor.submit(transfer_and_log, file) for file in pending_files if file.status in [TransferStatus.PENDING, TransferStatus.FAILED]]
            for future in as_completed(futures):
                pass
        
        # Refresh pending_files queryset for next retry
        pending_files = BackupFile.objects.filter(
            user=request.user,
            status=TransferStatus.PENDING
        )
        
        if pending_files.count() == 0:
            break
    
    # Final counts after retries
    final_pending = BackupFile.objects.filter(user=request.user, status=TransferStatus.PENDING).count()
    final_failed = BackupFile.objects.filter(user=request.user, status=TransferStatus.FAILED).count()
    final_success = BackupFile.objects.filter(user=request.user, status=TransferStatus.SUCCESS).count()
    total = final_pending + final_failed + final_success
    
    if final_failed == 0:
        messages.success(request, f'Successfully transferred all {total} files and folders after retries')
    else:
        messages.warning(request, f'Processed {total} items: {final_success} successful, {final_failed} failed after retries. Check file list for details.')
    
    return redirect('file_list')

@login_required
def process_transfer(request, file_id):
    """Process the actual file or folder transfer (would normally be a background task)"""
    # Get the file or folder or return 404
    backup_file = get_object_or_404(BackupFile, id=file_id, user=request.user)
    
    # Only process files/folders that are in_progress or retrying
    if backup_file.status not in [TransferStatus.IN_PROGRESS, TransferStatus.RETRYING]:
        messages.error(request, f'Cannot process {backup_file.filename} - not in progress')
        return redirect('file_detail', file_id=file_id)
    
    # Perform the file or folder transfer
    success, message = transfer_file(backup_file)
    
    if success:
        backup_file.status = TransferStatus.SUCCESS
        log_action = 'transfer_complete'
        messages.success(request, f'{backup_file.filename} transferred successfully')
    else:
        backup_file.status = TransferStatus.FAILED
        backup_file.error_message = message
        log_action = 'transfer_failed'
        messages.error(request, f'Transfer failed: {message}')
    
    # Update backup file/folder status
    backup_file.save()
    
    # Log the transfer result
    log_entry = TransferLog(
        backup_file=backup_file,
        action=log_action,
        message=message
    )
    log_entry.save()
    
    return redirect('file_detail', file_id=file_id)

@login_required
def retry_failed(request):
    """Retry all failed transfers and process them in one operation"""
    if request.method != 'POST':
        # Only allow POST requests
        return redirect('file_list')
    
    # Get all failed files and folders
    failed_files = BackupFile.objects.filter(
        user=request.user,
        status=TransferStatus.FAILED
    )
    
    count = failed_files.count()
    
    if count == 0:
        messages.info(request, 'No failed files or folders to retry')
        return redirect('file_list')
    
    success_count = 0
    failed_count = 0
    
    from concurrent.futures import ThreadPoolExecutor, as_completed
    
    def retry_and_log(file):
        nonlocal success_count, failed_count
        try:
            file.status = TransferStatus.RETRYING
            file.retry_count += 1
            file.save()
            
            init_log = TransferLog(
                backup_file=file,
                action='transfer_retry',
                message=f'Manual retry initiated by user (attempt #{file.retry_count})'
            )
            init_log.save()
            
            success, message = transfer_file(file)
            
            if success:
                file.status = TransferStatus.SUCCESS
                log_action = 'transfer_complete'
                success_count += 1
            else:
                file.status = TransferStatus.FAILED
                file.error_message = message
                log_action = 'transfer_failed'
                failed_count += 1
            
            file.save()
            
            result_log = TransferLog(
                backup_file=file,
                action=log_action,
                message=message
            )
            result_log.save()
        except Exception as e:
            failed_count += 1
            file.status = TransferStatus.FAILED
            file.error_message = str(e)
            file.save()
            log = TransferLog(
                backup_file=file,
                action='transfer_failed',
                message=f'Exception during retry: {str(e)}'
            )
            log.save()
    
    with ThreadPoolExecutor(max_workers=10) as executor:
        futures = [executor.submit(retry_and_log, file) for file in failed_files]
        for future in as_completed(futures):
            pass
    
    if failed_count == 0:
        messages.success(request, f'Successfully retried and transferred all {count} files and folders')
    else:
        messages.warning(request, f'Processed {count} retry attempts: {success_count} successful, {failed_count} failed. Check file list for details.')
    
    return redirect('file_list')

@login_required
def fix_file_paths(request):
    """Fix paths for all Python files to use the standardized format"""
    # Only allow admin users
    if not request.user.is_staff and not request.user.is_superuser:
        messages.error(request, 'You do not have permission to access this function')
        return redirect('dashboard')
    
    # Find all Python files
    files_to_fix = BackupFile.objects.filter(filename__endswith='.py')
    fixed_count = 0
    
    for file in files_to_fix:
        # Get the server configurations to use their proper paths
        source_server = file.source_server
        destination_server = file.destination_server
        
        # Fix paths using the configured remote paths from the server configs
        file.source_path = os.path.join(source_server.remote_path, file.filename).replace('\\', '/')
        file.destination_path = os.path.join(destination_server.remote_path, file.filename).replace('\\', '/')
        
        # Reset status to pending for retransfer if failed
        if file.status == TransferStatus.FAILED:
            file.status = TransferStatus.PENDING
            file.error_message = None
        
        # Save the changes
        file.save()
        
        # Add log entry
        log = TransferLog(
            backup_file=file,
            action='path_corrected',
            message=f'Corrected paths for file transfer: {file.source_path} -> {file.destination_path}'
        )
        log.save()
        fixed_count += 1
    
    messages.success(request, f'Fixed paths for {fixed_count} Python files')
    return redirect('file_list')

