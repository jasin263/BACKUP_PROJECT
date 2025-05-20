import os
from django.db import models
from django.contrib.auth.models import User
from django.utils import timezone

class TransferStatus(models.TextChoices):
    PENDING = 'pending', 'Pending'
    IN_PROGRESS = 'in_progress', 'In Progress'
    SUCCESS = 'success', 'Success'
    FAILED = 'failed', 'Failed'
    RETRYING = 'retrying', 'Retrying'

class ServerConfig(models.Model):
    name = models.CharField(max_length=64)
    host = models.CharField(max_length=120)
    port = models.IntegerField(default=22)
    username = models.CharField(max_length=64)
    password = models.CharField(max_length=256, blank=True, null=True)
    private_key = models.TextField(blank=True, null=True)
    remote_path = models.CharField(max_length=256)
    server_type = models.CharField(max_length=20)  # 'source' or 'destination'
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='server_configs')
    created_at = models.DateTimeField(default=timezone.now)
    
    def __str__(self):
        return f'{self.name} ({self.server_type})'

class BackupFile(models.Model):
    filename = models.CharField(max_length=256)
    file_size = models.BigIntegerField(blank=True, null=True)
    file_created_at = models.DateTimeField(blank=True, null=True)
    file_modified_at = models.DateTimeField(blank=True, null=True)
    source_path = models.CharField(max_length=512)
    destination_path = models.CharField(max_length=512)
    status = models.CharField(
        max_length=20,
        choices=TransferStatus.choices,
        default=TransferStatus.PENDING
    )
    error_message = models.TextField(blank=True, null=True)
    retry_count = models.IntegerField(default=0)
    created_at = models.DateTimeField(default=timezone.now)
    updated_at = models.DateTimeField(auto_now=True)
    source_server = models.ForeignKey(ServerConfig, on_delete=models.CASCADE, related_name='source_files')
    destination_server = models.ForeignKey(ServerConfig, on_delete=models.CASCADE, related_name='destination_files')
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='backup_files')
    is_folder = models.BooleanField(default=False)
    files_count = models.IntegerField(default=0)
    
    def __str__(self):
        return f'{self.filename} (Status: {self.status})'

class TransferLog(models.Model):
    backup_file = models.ForeignKey(BackupFile, on_delete=models.CASCADE, related_name='logs')
    action = models.CharField(max_length=64) # e.g., 'transfer_start', 'transfer_complete', 'retry'
    message = models.TextField(blank=True, null=True)
    timestamp = models.DateTimeField(default=timezone.now)
    
    def __str__(self):
        return f'{self.action} for file ID {self.backup_file_id}'

class ScheduleConfig(models.Model):
    name = models.CharField(max_length=64)
    source_server = models.ForeignKey(ServerConfig, on_delete=models.CASCADE, related_name='source_schedules')
    destination_server = models.ForeignKey(ServerConfig, on_delete=models.CASCADE, related_name='destination_schedules')
    frequency = models.CharField(max_length=20, default='daily')  # daily, hourly, weekly, etc.
    cron_expression = models.CharField(max_length=64, blank=True, null=True)  # For more complex schedules
    enabled = models.BooleanField(default=True)
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='schedules')
    created_at = models.DateTimeField(default=timezone.now)
    last_run = models.DateTimeField(null=True, blank=True)
    
    def __str__(self):
        return f'{self.name} (Frequency: {self.frequency})'
