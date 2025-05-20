import logging
from datetime import datetime
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from flask import Flask
from app import db
from models import ScheduleConfig, ServerConfig, BackupFile, TransferLog, TransferStatus
from utils import list_files_on_server, transfer_file
import os
import time

# Set up logger
logger = logging.getLogger(__name__)

# Initialize the scheduler
scheduler = BackgroundScheduler()

def scan_and_transfer_files(app, schedule_id):
    """Background job to scan source server and transfer files to destination"""
    with app.app_context():
        try:
            # Get the schedule configuration
            schedule = ScheduleConfig.query.get(schedule_id)
            
            if not schedule or not schedule.enabled:
                logger.warning(f"Schedule {schedule_id} not found or disabled")
                return
            
            logger.info(f"Starting scheduled job for config: {schedule.name}")
            
            # Update last run time
            schedule.last_run = datetime.now()
            db.session.commit()
            
            # Get server configurations
            source_server = ServerConfig.query.get(schedule.source_server_id)
            destination_server = ServerConfig.query.get(schedule.destination_server_id)
            
            if not source_server or not destination_server:
                logger.error(f"Source or destination server not found for schedule {schedule_id}")
                return
            
            # Scan for files on source server
            files = list_files_on_server(source_server)
            new_files_count = 0
            transfer_success_count = 0
            transfer_failed_count = 0
            
            # Process each file
            for file_info in files:
                # Check if file is already registered
                existing = BackupFile.query.filter_by(
                    filename=file_info['filename'],
                    source_server_id=source_server.id,
                    destination_server_id=destination_server.id,
                    user_id=schedule.user_id
                ).first()
                
                if not existing:
                    # Register new file for transfer
                    new_file = BackupFile(
                        filename=file_info['filename'],
                        file_size=file_info['size'],
                        file_created_at=file_info.get('created_at'),
                        file_modified_at=file_info.get('modified_at'),
                        source_path=os.path.join(source_server.remote_path, file_info['filename']),
                        destination_path=os.path.join(destination_server.remote_path, file_info['filename']),
                        status=TransferStatus.PENDING,
                        source_server_id=source_server.id,
                        destination_server_id=destination_server.id,
                        user_id=schedule.user_id
                    )
                    
                    db.session.add(new_file)
                    db.session.commit()
                    new_files_count += 1
                    
                    # Immediately attempt transfer
                    new_file.status = TransferStatus.IN_PROGRESS
                    db.session.commit()
                    
                    # Log the transfer initiation
                    log_entry = TransferLog(
                        backup_file_id=new_file.id,
                        action='transfer_initiated',
                        message='Scheduled automatic transfer'
                    )
                    db.session.add(log_entry)
                    db.session.commit()
                    
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
                    db.session.commit()
                    
                    # Log the transfer result
                    log_entry = TransferLog(
                        backup_file_id=new_file.id,
                        action=log_action,
                        message=message
                    )
                    db.session.add(log_entry)
                    db.session.commit()
                    
                    # Small delay between transfers to avoid overwhelming the server
                    time.sleep(1)
            
            logger.info(f"Scheduled job completed for config: {schedule.name}. "
                      f"Found {new_files_count} new files, transferred {transfer_success_count} successfully, "
                      f"{transfer_failed_count} failed.")
            
        except Exception as e:
            logger.error(f"Error in scheduled job for config {schedule_id}: {str(e)}")

def retry_failed_transfers(app):
    """Background job to retry failed transfers with exponential backoff"""
    with app.app_context():
        try:
            # Find failed transfers with retry count < 5
            failed_files = BackupFile.query.filter_by(status=TransferStatus.FAILED).filter(BackupFile.retry_count < 5).all()
            
            logger.info(f"Starting retry job for {len(failed_files)} failed transfers")
            
            retried_count = 0
            success_count = 0
            
            for backup_file in failed_files:
                # Update status and increment retry count
                backup_file.status = TransferStatus.RETRYING
                backup_file.retry_count += 1
                db.session.commit()
                
                # Log the retry attempt
                log_entry = TransferLog(
                    backup_file_id=backup_file.id,
                    action='transfer_retry',
                    message=f'Automatic retry attempt #{backup_file.retry_count}'
                )
                db.session.add(log_entry)
                db.session.commit()
                
                retried_count += 1
                
                # Perform the file transfer
                success, message = transfer_file(backup_file)
                
                if success:
                    backup_file.status = TransferStatus.SUCCESS
                    log_action = 'transfer_complete'
                    success_count += 1
                else:
                    backup_file.status = TransferStatus.FAILED
                    backup_file.error_message = message
                    log_action = 'transfer_failed'
                
                # Update backup file status
                db.session.commit()
                
                # Log the transfer result
                log_entry = TransferLog(
                    backup_file_id=backup_file.id,
                    action=log_action,
                    message=message
                )
                db.session.add(log_entry)
                db.session.commit()
                
                # Exponential backoff delay
                time.sleep(2 ** backup_file.retry_count)
            
            logger.info(f"Retry job completed. Retried {retried_count} transfers, {success_count} successful.")
            
        except Exception as e:
            logger.error(f"Error in retry job: {str(e)}")

def init_scheduler(app):
    """Initialize the background scheduler with all scheduled jobs"""
    try:
        # Ensure scheduler is not already running
        if scheduler.running:
            logger.warning("Scheduler already running, skipping initialization")
            return
        
        with app.app_context():
            # Add job to retry failed transfers every 15 minutes
            scheduler.add_job(
                func=retry_failed_transfers,
                args=[app],
                trigger='interval',
                minutes=15,
                id='retry_failed_transfers',
                replace_existing=True
            )
            
            # Add scheduled jobs for each enabled schedule
            schedules = ScheduleConfig.query.filter_by(enabled=True).all()
            
            for schedule in schedules:
                if schedule.cron_expression:
                    # Use custom cron expression if provided
                    trigger = CronTrigger.from_crontab(schedule.cron_expression)
                else:
                    # Default schedules based on frequency
                    if schedule.frequency == 'hourly':
                        trigger = 'interval'
                        kwargs = {'hours': 1}
                    elif schedule.frequency == 'daily':
                        trigger = 'cron'
                        kwargs = {'hour': 0, 'minute': 0}
                    elif schedule.frequency == 'weekly':
                        trigger = 'cron'
                        kwargs = {'day_of_week': 0, 'hour': 0, 'minute': 0}
                    else:
                        # Default to daily
                        trigger = 'cron'
                        kwargs = {'hour': 0, 'minute': 0}
                
                # Add the job to the scheduler
                if isinstance(trigger, str) and trigger == 'interval':
                    scheduler.add_job(
                        func=scan_and_transfer_files,
                        args=[app, schedule.id],
                        trigger=trigger,
                        **kwargs,
                        id=f'schedule_{schedule.id}',
                        replace_existing=True
                    )
                else:
                    scheduler.add_job(
                        func=scan_and_transfer_files,
                        args=[app, schedule.id],
                        trigger=trigger,
                        id=f'schedule_{schedule.id}',
                        replace_existing=True
                    )
                
                logger.info(f"Added scheduled job for config: {schedule.name}")
        
        # Start the scheduler
        scheduler.start()
        logger.info("Background scheduler started successfully")
        
    except Exception as e:
        logger.error(f"Error initializing scheduler: {str(e)}")
