import logging
import os
import paramiko
import io
from datetime import datetime
from flask import render_template, redirect, url_for, flash, request, jsonify
from flask_login import login_required, current_user
from app import app, db
from models import ServerConfig, BackupFile, TransferLog, TransferStatus
from forms import ServerConfigForm
from utils import sftp_connect, list_files_on_server, transfer_file

# Set up logger
logger = logging.getLogger(__name__)

@app.route('/dashboard')
@login_required
def dashboard():
    """Main dashboard view showing backup files status and statistics"""
    # Get counts for different file statuses
    status_counts = {
        'pending': BackupFile.query.filter_by(user_id=current_user.id, status=TransferStatus.PENDING).count(),
        'in_progress': BackupFile.query.filter_by(user_id=current_user.id, status=TransferStatus.IN_PROGRESS).count(),
        'success': BackupFile.query.filter_by(user_id=current_user.id, status=TransferStatus.SUCCESS).count(),
        'failed': BackupFile.query.filter_by(user_id=current_user.id, status=TransferStatus.FAILED).count(),
        'retrying': BackupFile.query.filter_by(user_id=current_user.id, status=TransferStatus.RETRYING).count()
    }
    
    # Get the most recent files
    recent_files = BackupFile.query.filter_by(user_id=current_user.id).order_by(BackupFile.updated_at.desc()).limit(10).all()
    
    # Get available server configurations
    source_servers = ServerConfig.query.filter_by(user_id=current_user.id, server_type='source').all()
    destination_servers = ServerConfig.query.filter_by(user_id=current_user.id, server_type='destination').all()
    
    return render_template('dashboard.html', 
                          status_counts=status_counts, 
                          recent_files=recent_files,
                          source_servers=source_servers,
                          destination_servers=destination_servers)

@app.route('/files')
@login_required
def file_list():
    """View all backup files with filtering options"""
    status_filter = request.args.get('status', '')
    
    # Base query for user's files
    query = BackupFile.query.filter_by(user_id=current_user.id)
    
    # Apply status filter if provided
    if status_filter and status_filter != 'all':
        query = query.filter_by(status=status_filter)
    
    # Get files with pagination
    page = request.args.get('page', 1, type=int)
    files = query.order_by(BackupFile.updated_at.desc()).paginate(page=page, per_page=20)
    
    return render_template('file_list.html', 
                          files=files,
                          current_status=status_filter)

@app.route('/settings', methods=['GET', 'POST'])
@login_required
def settings():
    """User settings page for configuring servers"""
    form = ServerConfigForm()
    
    if form.validate_on_submit():
        # Create new server configuration
        new_server = ServerConfig(
            name=form.name.data,
            host=form.host.data,
            port=form.port.data,
            username=form.username.data,
            password=form.password.data if form.auth_type.data == 'password' else None,
            private_key=form.private_key.data if form.auth_type.data == 'key' else None,
            remote_path=form.remote_path.data,
            server_type=form.server_type.data,
            user_id=current_user.id
        )
        
        db.session.add(new_server)
        db.session.commit()
        
        flash(f'Server "{new_server.name}" has been added successfully', 'success')
        return redirect(url_for('settings'))
    
    # Get user's server configurations
    source_servers = ServerConfig.query.filter_by(user_id=current_user.id, server_type='source').all()
    destination_servers = ServerConfig.query.filter_by(user_id=current_user.id, server_type='destination').all()
    
    return render_template('settings.html', 
                          form=form,
                          source_servers=source_servers,
                          destination_servers=destination_servers)

@app.route('/server/delete/<int:server_id>', methods=['POST'])
@login_required
def delete_server(server_id):
    """Delete a server configuration"""
    server = ServerConfig.query.filter_by(id=server_id, user_id=current_user.id).first_or_404()
    
    # Check for associated backup files
    associated_files = BackupFile.query.filter(
        (BackupFile.source_server_id == server_id) | 
        (BackupFile.destination_server_id == server_id)
    ).first()
    
    if associated_files:
        flash('Cannot delete server as it has associated backup files', 'danger')
    else:
        db.session.delete(server)
        db.session.commit()
        flash(f'Server "{server.name}" has been deleted', 'success')
    
    return redirect(url_for('settings'))

@app.route('/scan_files', methods=['POST'])
@login_required
def scan_files():
    """Scan source server for backup files and register them for transfer"""
    source_id = request.form.get('source_server')
    destination_id = request.form.get('destination_server')
    
    if not source_id or not destination_id:
        flash('Please select both source and destination servers', 'danger')
        return redirect(url_for('dashboard'))
    
    try:
        source_server = ServerConfig.query.filter_by(id=source_id, user_id=current_user.id).first_or_404()
        destination_server = ServerConfig.query.filter_by(id=destination_id, user_id=current_user.id).first_or_404()
        
        # Connect to source server and list files
        files = list_files_on_server(source_server)
        count = 0
        
        for file_info in files:
            # Check if file is already registered
            existing = BackupFile.query.filter_by(
                filename=file_info['filename'],
                source_server_id=source_server.id,
                destination_server_id=destination_server.id,
                user_id=current_user.id
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
                    user_id=current_user.id
                )
                
                db.session.add(new_file)
                count += 1
        
        db.session.commit()
        flash(f'Found and registered {count} new files for transfer', 'success')
        
    except Exception as e:
        logger.error(f"Error scanning files: {str(e)}")
        flash(f'Error scanning files: {str(e)}', 'danger')
    
    return redirect(url_for('dashboard'))

@app.route('/transfer/<int:file_id>', methods=['POST'])
@login_required
def initiate_transfer(file_id):
    """Manually initiate transfer for a specific file"""
    backup_file = BackupFile.query.filter_by(id=file_id, user_id=current_user.id).first_or_404()
    
    # Only allow transfer if file is in pending or failed status
    if backup_file.status not in [TransferStatus.PENDING, TransferStatus.FAILED]:
        flash(f'Cannot initiate transfer for file with status: {backup_file.status}', 'warning')
        return redirect(url_for('file_list'))
    
    try:
        # Update status to in progress
        backup_file.status = TransferStatus.IN_PROGRESS
        db.session.commit()
        
        # Log the transfer initiation
        log_entry = TransferLog(
            backup_file_id=backup_file.id,
            action='transfer_initiated',
            message='Manual transfer initiated'
        )
        db.session.add(log_entry)
        db.session.commit()
        
        # Perform the file transfer
        success, message = transfer_file(backup_file)
        
        if success:
            backup_file.status = TransferStatus.SUCCESS
            log_action = 'transfer_complete'
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
        
        flash(f'Transfer {"completed successfully" if success else "failed"}', 'success' if success else 'danger')
        
    except Exception as e:
        logger.error(f"Error during file transfer: {str(e)}")
        backup_file.status = TransferStatus.FAILED
        backup_file.error_message = str(e)
        db.session.commit()
        
        flash(f'Error during file transfer: {str(e)}', 'danger')
    
    return redirect(url_for('file_list'))

@app.route('/file/logs/<int:file_id>')
@login_required
def file_logs(file_id):
    """View logs for a specific file"""
    backup_file = BackupFile.query.filter_by(id=file_id, user_id=current_user.id).first_or_404()
    logs = TransferLog.query.filter_by(backup_file_id=file_id).order_by(TransferLog.timestamp.desc()).all()
    
    return render_template('file_logs.html', file=backup_file, logs=logs)

@app.route('/admin')
@login_required
def admin_panel():
    """Admin panel for system management (admin users only)"""
    if not current_user.is_admin:
        flash('You do not have permission to access the admin panel', 'danger')
        return redirect(url_for('dashboard'))
    
    # Get all users
    users = User.query.all()
    
    # Get system-wide transfer statistics
    status_counts = {
        'pending': BackupFile.query.filter_by(status=TransferStatus.PENDING).count(),
        'in_progress': BackupFile.query.filter_by(status=TransferStatus.IN_PROGRESS).count(),
        'success': BackupFile.query.filter_by(status=TransferStatus.SUCCESS).count(),
        'failed': BackupFile.query.filter_by(status=TransferStatus.FAILED).count(),
        'retrying': BackupFile.query.filter_by(status=TransferStatus.RETRYING).count()
    }
    
    # Get recent failed transfers
    failed_files = BackupFile.query.filter_by(status=TransferStatus.FAILED).order_by(BackupFile.updated_at.desc()).limit(10).all()
    
    return render_template('admin.html', 
                          users=users,
                          status_counts=status_counts,
                          failed_files=failed_files)
