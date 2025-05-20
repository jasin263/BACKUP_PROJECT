from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.db.models import Count
from django.http import JsonResponse
from django.urls import reverse
from ..models import ServerConfig, BackupFile, TransferLog, ScheduleConfig, TransferStatus

@login_required
def dashboard(request):
    """Main dashboard view showing backup files status and statistics"""
    # Get user's backup files statistics
    files_count = BackupFile.objects.filter(user=request.user).count()
    pending_count = BackupFile.objects.filter(user=request.user, status=TransferStatus.PENDING).count()
    in_progress_count = BackupFile.objects.filter(user=request.user, status=TransferStatus.IN_PROGRESS).count()
    success_count = BackupFile.objects.filter(user=request.user, status=TransferStatus.SUCCESS).count()
    failed_count = BackupFile.objects.filter(user=request.user, status=TransferStatus.FAILED).count()
    retrying_count = BackupFile.objects.filter(user=request.user, status=TransferStatus.RETRYING).count()
    
    # Get recent transfers (last 5)
    recent_transfers = BackupFile.objects.filter(user=request.user).order_by('-updated_at')[:5]
    
    # Get user's servers and schedules
    servers_count = ServerConfig.objects.filter(user=request.user).count()
    schedules_count = ScheduleConfig.objects.filter(user=request.user).count()
    active_schedules = ScheduleConfig.objects.filter(user=request.user, enabled=True).count()
    
    # Prepare data for the template
    context = {
        'title': 'Dashboard',
        'files_count': files_count,
        'pending_count': pending_count,
        'in_progress_count': in_progress_count,
        'success_count': success_count,
        'failed_count': failed_count,
        'retrying_count': retrying_count,
        'recent_transfers': recent_transfers,
        'servers_count': servers_count,
        'schedules_count': schedules_count,
        'active_schedules': active_schedules,
    }
    
    return render(request, 'backup_app/dashboard.html', context)

@login_required
def file_list(request):
    """View all backup files with filtering options"""
    # Get filter parameters from query string
    status_filter = request.GET.get('status', '')
    server_filter = request.GET.get('server', '')
    search_query = request.GET.get('search', '')
    
    # Base query: all files for current user
    files = BackupFile.objects.filter(user=request.user)
    
    # Apply filters if provided
    if status_filter and status_filter != 'all':
        files = files.filter(status=status_filter)
    
    if server_filter and server_filter != 'all':
        server_id = int(server_filter)
        files = files.filter(source_server_id=server_id) | files.filter(destination_server_id=server_id)
    
    if search_query:
        files = files.filter(filename__icontains=search_query)
    
    # Order by latest updated
    files = files.order_by('-updated_at')
    
    # Get user's servers for filter dropdown
    servers = ServerConfig.objects.filter(user=request.user)
    
    # Prepare data for the template
    context = {
        'title': 'Backup Files',
        'files': files,
        'servers': servers,
        'status_filter': status_filter,
        'server_filter': server_filter,
        'search_query': search_query,
        'status_choices': TransferStatus.choices,
    }
    
    return render(request, 'backup_app/file_list.html', context)

@login_required
def file_detail(request, file_id):
    """View details and logs for a specific file"""
    # Get the file or return 404
    backup_file = get_object_or_404(BackupFile, id=file_id, user=request.user)
    
    # Get all logs for this file
    logs = TransferLog.objects.filter(backup_file=backup_file).order_by('-timestamp')
    
    # Prepare data for the template
    context = {
        'title': f'File Details: {backup_file.filename}',
        'file': backup_file,
        'logs': logs,
    }
    
    return render(request, 'backup_app/file_detail.html', context)

@login_required
def initiate_transfer(request, file_id):
    """Manually initiate transfer for a specific file"""
    # Only allow POST requests
    if request.method != 'POST':
        return JsonResponse({'error': 'Method not allowed'}, status=405)
    
    # Get the file or return 404
    backup_file = get_object_or_404(BackupFile, id=file_id, user=request.user)
    
    # Check if the file is in a state that allows transfer
    if backup_file.status in [TransferStatus.IN_PROGRESS, TransferStatus.RETRYING]:
        return JsonResponse({'error': 'Transfer already in progress'}, status=400)
    
    # Update status to in_progress
    backup_file.status = TransferStatus.IN_PROGRESS
    backup_file.save()
    
    # Log the manual transfer initiation
    log = TransferLog(
        backup_file=backup_file,
        action='transfer_initiated',
        message='Manual transfer initiated by user'
    )
    log.save()
    
    # Queue the transfer (in a real app, this might be a background task)
    # For now, we'll just redirect and let the view handle the transfer
    return JsonResponse({'success': True, 'message': 'Transfer initiated', 'redirect': reverse('file_detail', args=[file_id])})

@login_required
def cancel_transfer(request, file_id):
    """Cancel an in-progress or pending transfer"""
    # Only allow POST requests
    if request.method != 'POST':
        return JsonResponse({'error': 'Method not allowed'}, status=405)
    
    # Get the file or return 404
    backup_file = get_object_or_404(BackupFile, id=file_id, user=request.user)
    
    # Check if the file is in a state that allows cancellation
    if backup_file.status not in [TransferStatus.PENDING, TransferStatus.IN_PROGRESS, TransferStatus.RETRYING]:
        return JsonResponse({'error': 'Cannot cancel a completed or failed transfer'}, status=400)
    
    # Update status to cancelled (using FAILED for now, could add a CANCELLED status)
    backup_file.status = TransferStatus.FAILED
    backup_file.error_message = 'Transfer cancelled by user'
    backup_file.save()
    
    # Log the cancellation
    log = TransferLog(
        backup_file=backup_file,
        action='transfer_cancelled',
        message='Transfer cancelled by user'
    )
    log.save()
    
    return JsonResponse({'success': True, 'message': 'Transfer cancelled', 'redirect': reverse('file_detail', args=[file_id])})
