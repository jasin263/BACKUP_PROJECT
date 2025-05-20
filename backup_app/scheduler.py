import logging
import time
import os
from datetime import datetime
from django.utils import timezone
from django_apscheduler.jobstores import DjangoJobStore
from django_apscheduler.models import DjangoJobExecution
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from .models import BackupFile, ScheduleConfig, TransferLog, TransferStatus
from .utils import list_files_on_server, transfer_file
from concurrent.futures import ThreadPoolExecutor, as_completed

# Set up logger
logger = logging.getLogger(__name__)

def delete_old_job_executions(max_age=604_800):
    """Delete job execution entries older than `max_age` seconds."""
    DjangoJobExecution.objects.delete_old_job_executions(max_age)

def scan_and_transfer_files(schedule_id):
    """Background job to scan source server and transfer files to destination"""
    try:
        # Get the schedule configuration
        schedule = ScheduleConfig.objects.get(pk=schedule_id)
        
        if not schedule or not schedule.enabled:
            logger.warning(f"Schedule {schedule_id} not found or disabled")
            return
        
        logger.info(f"Starting scheduled job for config: {schedule.name}")
        
        # Update last run time
        schedule.last_run = timezone.now()
        schedule.save()
        
        # Get server configurations
        source_server = schedule.source_server
        destination_server = schedule.destination_server
        
        new_files_count = 0
        transfer_success_count = 0
        transfer_failed_count = 0
        
        # Scan for files on source server only if scanning is enabled for this schedule
        if getattr(schedule, 'scan_enabled', True):
            files = list_files_on_server(source_server, include_folders=True)
            
            # Function to transfer a single file and log results
            def transfer_and_log(file_info):
                nonlocal transfer_success_count, transfer_failed_count
                try:
                    # Check if file is already registered
                    existing = BackupFile.objects.filter(
                        filename=file_info['filename'],
                        source_server=source_server,
                        destination_server=destination_server,
                        user=schedule.user
                    ).first()
                    
                    if not existing:
                        # Register new file for transfer
                        new_file = BackupFile(
                            filename=file_info['filename'],
                            file_size=file_info['size'],
                            file_created_at=file_info.get('created_at'),
                            file_modified_at=file_info.get('modified_at'),
                            source_path=os.path.join(source_server.remote_path, file_info['filename']).replace('\\', '/'),
                            destination_path=os.path.join(destination_server.remote_path, file_info['filename']).replace('\\', '/'),
                            status=TransferStatus.PENDING,
                            source_server=source_server,
                            destination_server=destination_server,
                            user=schedule.user,
                            is_folder=file_info.get('is_folder', False)
                        )
                        
                        new_file.save()
                        # Immediately attempt transfer
                        new_file.status = TransferStatus.IN_PROGRESS
                        new_file.save()
                        
                        # Log the transfer initiation
                        log_entry = TransferLog(
                            backup_file=new_file,
                            action='transfer_initiated',
                            message='Scheduled automatic transfer'
                        )
                        log_entry.save()
                        
                        # Perform the file transfer
                        success, message = transfer_file(new_file)
                        
                        if success:
                            new_file.status = TransferStatus.SUCCESS
                            log_action = 'transfer_complete'
                            transfer_success_count += 1
                        else:
                            new_file.status = TransferStatus.FAILED
                            new_file.error_message = message
                            log_action = 'transfer_failed'
                            transfer_failed_count += 1
                        
                        # Update backup file status
                        new_file.save()
                        
                        # Log the transfer result
                        log_entry = TransferLog(
                            backup_file=new_file,
                            action=log_action,
                            message=message
                        )
                        log_entry.save()
                except Exception as e:
                    logger.error(f"Error transferring file {file_info['filename']}: {str(e)}")
                    transfer_failed_count += 1
            
            # Use ThreadPoolExecutor to transfer files concurrently
            with ThreadPoolExecutor(max_workers=10) as executor:
                futures = [executor.submit(transfer_and_log, file_info) for file_info in files]
                for future in as_completed(futures):
                    pass  # Just wait for all to complete
        
        # Transfer all pending files regardless of scanning
        pending_files = BackupFile.objects.filter(
            user=schedule.user,
            status=TransferStatus.PENDING,
            source_server=source_server,
            destination_server=destination_server
        )   
        
        def transfer_pending_file(backup_file):
            nonlocal transfer_success_count, transfer_failed_count
            try:
                backup_file.status = TransferStatus.IN_PROGRESS
                backup_file.save()
                
                log_entry = TransferLog(
                    backup_file=backup_file,
                    action='transfer_initiated',
                    message='Scheduled automatic transfer of pending file'
                )
                log_entry.save()
                
                success, message = transfer_file(backup_file)
                
                if success:
                    backup_file.status = TransferStatus.SUCCESS
                    log_action = 'transfer_complete'
                    transfer_success_count += 1
                else:
                    backup_file.status = TransferStatus.FAILED
                    backup_file.error_message = message
                    log_action = 'transfer_failed'
                    transfer_failed_count += 1
                
                backup_file.save()
                
                log_entry = TransferLog(
                    backup_file=backup_file,
                    action=log_action,
                    message=message
                )
                log_entry.save()
            except Exception as e:
                logger.error(f"Error transferring pending file {backup_file.filename}: {str(e)}")
                transfer_failed_count += 1
        
        with ThreadPoolExecutor(max_workers=10) as executor:
            futures = [executor.submit(transfer_pending_file, bf) for bf in pending_files]
            for future in as_completed(futures):
                pass
        
        logger.info(f"Scheduled job completed for config: {schedule.name}. "
                    f"Transferred {transfer_success_count} files successfully, "
                    f"{transfer_failed_count} failed.")
        
    except Exception as e:
        logger.error(f"Error in scheduled job for config {schedule_id}: {str(e)}")


def retry_failed_transfers():
    """Background job to retry all failed transfers concurrently"""
    from concurrent.futures import ThreadPoolExecutor, as_completed
    try:
        # Find all failed transfers regardless of retry count
        failed_files = BackupFile.objects.filter(status=TransferStatus.FAILED)
        
        logger.info(f"Starting retry job for {failed_files.count()} failed transfers")
        
        retried_count = 0
        success_count = 0
        
        def retry_transfer(backup_file):
            nonlocal success_count
            try:
                backup_file.status = TransferStatus.RETRYING
                backup_file.retry_count += 1
                backup_file.save()
                
                log_entry = TransferLog(
                    backup_file=backup_file,
                    action='transfer_retry',
                    message=f'Automatic retry attempt #{backup_file.retry_count}'
                )
                log_entry.save()
                
                success, message = transfer_file(backup_file)
                
                if success:
                    backup_file.status = TransferStatus.SUCCESS
                    log_action = 'transfer_complete'
                    success_count += 1
                else:
                    backup_file.status = TransferStatus.FAILED
                    backup_file.error_message = message
                    log_action = 'transfer_failed'
                
                backup_file.save()
                
                log_entry = TransferLog(
                    backup_file=backup_file,
                    action=log_action,
                    message=message
                )
                log_entry.save()
            except Exception as e:
                logger.error(f"Error retrying transfer for file {backup_file.filename}: {str(e)}")
        
        with ThreadPoolExecutor(max_workers=10) as executor:
            futures = [executor.submit(retry_transfer, bf) for bf in failed_files]
            for future in as_completed(futures):
                pass
        
        logger.info(f"Retry job completed. Retried {failed_files.count()} transfers, {success_count} successful.")
    except RuntimeError as e:
        if "cannot schedule new futures after interpreter shutdown" in str(e):
            logger.warning("Executor shutdown prevented scheduling new futures during interpreter shutdown")
        else:
            raise
    except Exception as e:
        logger.error(f"Error in retry job: {str(e)}")


def init_scheduler():
    """Initialize the background scheduler with scheduled jobs"""
    scheduler = BackgroundScheduler()
    scheduler.add_jobstore(DjangoJobStore(), "default")
    
    # Add job to retry failed transfers every 15 minutes
    scheduler.add_job(
        retry_failed_transfers,
        trigger='interval',
        minutes=15,
        id='retry_failed_transfers',
        replace_existing=True,
    )
    
    # Add job to delete old job executions daily
    scheduler.add_job(
        delete_old_job_executions,
        trigger=CronTrigger(hour="00", minute="00"),
        id="delete_old_job_executions",
        max_instances=1,
        replace_existing=True,
    )
    
    # Add scheduled jobs for each enabled schedule
    schedules = ScheduleConfig.objects.filter(enabled=True)
    
    for schedule in schedules:
        if schedule.cron_expression:
            # Use custom cron expression if provided
            trigger = CronTrigger.from_crontab(schedule.cron_expression)
            scheduler.add_job(
                scan_and_transfer_files,
                args=[schedule.id],
                trigger=trigger,
                id=f'schedule_{schedule.id}',
                replace_existing=True,
            )
        else:
            # Default schedules based on frequency
            if schedule.frequency == 'hourly':
                scheduler.add_job(
                    scan_and_transfer_files,
                    args=[schedule.id],
                    trigger='interval',
                    hours=1,
                    id=f'schedule_{schedule.id}',
                    replace_existing=True,
                )
            elif schedule.frequency == 'daily':
                scheduler.add_job(
                    scan_and_transfer_files,
                    args=[schedule.id],
                    trigger=CronTrigger(hour=0, minute=0),
                    id=f'schedule_{schedule.id}',
                    replace_existing=True,
                )
            elif schedule.frequency == 'weekly':
                scheduler.add_job(
                    scan_and_transfer_files,
                    args=[schedule.id],
                    trigger=CronTrigger(day_of_week=0, hour=0, minute=0),
                    id=f'schedule_{schedule.id}',
                    replace_existing=True,
                )
            
        logger.info(f"Added scheduled job for config: {schedule.name}")
    
    logger.info("Starting scheduler...")
    scheduler.start()
    return scheduler
