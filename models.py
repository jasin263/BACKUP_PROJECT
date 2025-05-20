import datetime
from app import db
from flask_login import UserMixin
from sqlalchemy import DateTime
from sqlalchemy.sql import func
from enum import Enum

class TransferStatus(str, Enum):
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    SUCCESS = "success"
    FAILED = "failed"
    RETRYING = "retrying"

class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(64), unique=True, nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False)
    password_hash = db.Column(db.String(256), nullable=False)
    is_admin = db.Column(db.Boolean, default=False)
    created_at = db.Column(DateTime(timezone=True), default=func.now())
    
    # Relationships
    server_configs = db.relationship('ServerConfig', backref='owner', lazy=True)
    transfers = db.relationship('BackupFile', backref='owner', lazy=True)
    
    def __repr__(self):
        return f'<User {self.username}>'

class ServerConfig(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(64), nullable=False)
    host = db.Column(db.String(120), nullable=False)
    port = db.Column(db.Integer, default=22)
    username = db.Column(db.String(64), nullable=False)
    password = db.Column(db.String(256), nullable=True)
    private_key = db.Column(db.Text, nullable=True)
    remote_path = db.Column(db.String(256), nullable=False)
    server_type = db.Column(db.String(20), nullable=False)  # 'source' or 'destination'
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    created_at = db.Column(DateTime(timezone=True), default=func.now())
    
    def __repr__(self):
        return f'<ServerConfig {self.name} ({self.server_type})>'

class BackupFile(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    filename = db.Column(db.String(256), nullable=False)
    file_size = db.Column(db.BigInteger, nullable=True)
    file_created_at = db.Column(DateTime(timezone=True), nullable=True)
    file_modified_at = db.Column(DateTime(timezone=True), nullable=True)
    source_path = db.Column(db.String(512), nullable=False)
    destination_path = db.Column(db.String(512), nullable=False)
    status = db.Column(db.String(20), default=TransferStatus.PENDING)
    error_message = db.Column(db.Text, nullable=True)
    retry_count = db.Column(db.Integer, default=0)
    created_at = db.Column(DateTime(timezone=True), default=func.now())
    updated_at = db.Column(DateTime(timezone=True), onupdate=func.now(), default=func.now())
    source_server_id = db.Column(db.Integer, db.ForeignKey('server_config.id'), nullable=False)
    destination_server_id = db.Column(db.Integer, db.ForeignKey('server_config.id'), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    
    # Relationships
    source_server = db.relationship('ServerConfig', foreign_keys=[source_server_id])
    destination_server = db.relationship('ServerConfig', foreign_keys=[destination_server_id])
    
    def __repr__(self):
        return f'<BackupFile {self.filename} (Status: {self.status})>'

class TransferLog(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    backup_file_id = db.Column(db.Integer, db.ForeignKey('backup_file.id'), nullable=False)
    action = db.Column(db.String(64), nullable=False)  # e.g., 'transfer_start', 'transfer_complete', 'retry'
    message = db.Column(db.Text, nullable=True)
    timestamp = db.Column(DateTime(timezone=True), default=func.now())
    
    # Relationship
    backup_file = db.relationship('BackupFile', backref='logs')
    
    def __repr__(self):
        return f'<TransferLog {self.action} for file ID {self.backup_file_id}>'

class ScheduleConfig(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(64), nullable=False)
    source_server_id = db.Column(db.Integer, db.ForeignKey('server_config.id'), nullable=False)
    destination_server_id = db.Column(db.Integer, db.ForeignKey('server_config.id'), nullable=False)
    frequency = db.Column(db.String(20), default="daily")  # daily, hourly, weekly, etc.
    cron_expression = db.Column(db.String(64), nullable=True)  # For more complex schedules
    enabled = db.Column(db.Boolean, default=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    created_at = db.Column(DateTime(timezone=True), default=func.now())
    last_run = db.Column(DateTime(timezone=True), nullable=True)
    
    # Relationships
    source_server = db.relationship('ServerConfig', foreign_keys=[source_server_id])
    destination_server = db.relationship('ServerConfig', foreign_keys=[destination_server_id])
    user = db.relationship('User', backref='schedules')
    
    def __repr__(self):
        return f'<ScheduleConfig {self.name} (Frequency: {self.frequency})>'
