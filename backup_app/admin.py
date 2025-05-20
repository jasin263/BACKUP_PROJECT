from django.contrib import admin
from .models import ServerConfig, BackupFile, TransferLog, ScheduleConfig

@admin.register(ServerConfig)
class ServerConfigAdmin(admin.ModelAdmin):
    list_display = ('name', 'host', 'port', 'username', 'server_type', 'user')
    list_filter = ('server_type', 'user')
    search_fields = ('name', 'host')

@admin.register(BackupFile)
class BackupFileAdmin(admin.ModelAdmin):
    list_display = ('filename', 'status', 'source_server', 'destination_server', 'user', 'updated_at')
    list_filter = ('status', 'source_server', 'destination_server', 'user')
    search_fields = ('filename',)

@admin.register(TransferLog)
class TransferLogAdmin(admin.ModelAdmin):
    list_display = ('action', 'backup_file', 'timestamp')
    list_filter = ('action',)
    search_fields = ('message',)

@admin.register(ScheduleConfig)
class ScheduleConfigAdmin(admin.ModelAdmin):
    list_display = ('name', 'frequency', 'source_server', 'destination_server', 'enabled', 'user')
    list_filter = ('frequency', 'enabled', 'user')
    search_fields = ('name',)

