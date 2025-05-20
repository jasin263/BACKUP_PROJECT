from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.http import JsonResponse
from django.urls import reverse
from ..models import ServerConfig, ScheduleConfig, BackupFile
from ..forms import ServerConfigForm, ScheduleConfigForm
from ..utils import list_files_on_server
import os

@login_required
def server_list(request):
    """View all server configurations"""
    # Get all servers for the current user
    source_servers = ServerConfig.objects.filter(user=request.user, server_type='source')
    destination_servers = ServerConfig.objects.filter(user=request.user, server_type='destination')
    
    context = {
        'title': 'Server Configurations',
        'source_servers': source_servers,
        'destination_servers': destination_servers,
    }
    
    return render(request, 'backup_app/server_list.html', context)

@login_required
def add_server(request):
    """Add a new server configuration"""
    if request.method == 'POST':
        form = ServerConfigForm(request.POST)
        if form.is_valid():
            # Create a new server but don't save to DB yet
            server = form.save(commit=False)
            # Add the current user
            server.user = request.user
            
            # Set password or private key based on auth_type field
            auth_type = form.cleaned_data.get('auth_type')
            if auth_type == 'password':
                server.private_key = None  # Clear private key if auth type is password
            else:  # auth_type == 'key'
                server.password = None  # Clear password if auth type is private key
                
            # Save the server to DB
            server.save()
            
            messages.success(request, f'Server {server.name} has been added!')
            return redirect('server_list')
    else:
        form = ServerConfigForm()
    
    context = {
        'title': 'Add Server',
        'form': form,
    }
    
    return render(request, 'backup_app/server_form.html', context)

@login_required
def edit_server(request, server_id):
    """Edit an existing server configuration"""
    # Get the server or return 404
    server = get_object_or_404(ServerConfig, id=server_id, user=request.user)
    
    if request.method == 'POST':
        form = ServerConfigForm(request.POST, instance=server)
        if form.is_valid():
            # Update server but don't save to DB yet
            updated_server = form.save(commit=False)
            
            # Set password or private key based on auth_type field
            auth_type = form.cleaned_data.get('auth_type')
            if auth_type == 'password':
                updated_server.private_key = None  # Clear private key if auth type is password
            else:  # auth_type == 'key'
                updated_server.password = None  # Clear password if auth type is private key
                
            # Save the updated server to DB
            updated_server.save()
            
            messages.success(request, f'Server {updated_server.name} has been updated!')
            return redirect('server_list')
    else:
        # Set initial auth_type based on whether password or private key is set
        initial_auth_type = 'password' if server.password else 'key'
        form = ServerConfigForm(instance=server, initial={'auth_type': initial_auth_type})
    
    context = {
        'title': 'Edit Server',
        'form': form,
        'server': server,
    }
    
    return render(request, 'backup_app/server_form.html', context)

@login_required
def delete_server(request, server_id):
    """Delete a server configuration"""
    # Only allow POST requests
    if request.method != 'POST':
        return JsonResponse({'error': 'Method not allowed'}, status=405)
    
    # Get the server or return 404
    server = get_object_or_404(ServerConfig, id=server_id, user=request.user)
    
    # Check if force delete parameter was passed
    force_delete = request.POST.get('force_delete') == 'true'
    
    # Check if there are any backup files associated with this server
    associated_files = BackupFile.objects.filter(
        user=request.user
    ).filter(
        source_server=server
    ) | BackupFile.objects.filter(
        user=request.user
    ).filter(
        destination_server=server
    )
    
    if associated_files.exists() and not force_delete:
        return JsonResponse({
            'error': 'Cannot delete server with associated backup files',
            'has_files': True,
            'file_count': associated_files.count()
        }, status=400)
    
    # Check if there are any schedules associated with this server
    associated_schedules = ScheduleConfig.objects.filter(
        user=request.user
    ).filter(
        source_server=server
    ) | ScheduleConfig.objects.filter(
        user=request.user
    ).filter(
        destination_server=server
    )
    
    if associated_schedules.exists():
        return JsonResponse({
            'error': 'Cannot delete server with associated schedules',
            'has_schedules': True,
            'schedule_count': associated_schedules.count()
        }, status=400)
    
    # If force delete, delete associated files first
    if force_delete and associated_files.exists():
        file_count = associated_files.count()
        associated_files.delete()
    else:
        file_count = 0
    
    # Delete the server
    server_name = server.name
    server.delete()
    
    if force_delete and file_count > 0:
        return JsonResponse({
            'success': True, 
            'message': f'Server {server_name} has been deleted along with {file_count} associated backup files'
        })
    else:
        return JsonResponse({
            'success': True, 
            'message': f'Server {server_name} has been deleted'
        })

@login_required
def test_server_connection(request, server_id):
    """Test connection to a server"""
    # Only allow POST requests
    if request.method != 'POST':
        return JsonResponse({'error': 'Method not allowed'}, status=405)
    
    # Get the server or return 404
    server = get_object_or_404(ServerConfig, id=server_id, user=request.user)
    
    try:
        # Try to list files and folders on the server
        files = list_files_on_server(server, include_folders=True)
        
        # Return success message with file and folder count
        return JsonResponse({
            'success': True, 
            'message': f'Connection successful! Found {len(files)} files and folders in the remote directory.'
        })
        
    except Exception as e:
        # Return error message
        return JsonResponse({'error': str(e)}, status=400)

@login_required
def schedule_list(request):
    """View all schedule configurations"""
    # Get all schedules for the current user
    schedules = ScheduleConfig.objects.filter(user=request.user)
    
    context = {
        'title': 'Backup Schedules',
        'schedules': schedules,
    }
    
    return render(request, 'backup_app/schedule_list.html', context)

@login_required
def add_schedule(request):
    """Add a new schedule configuration"""
    if request.method == 'POST':
        form = ScheduleConfigForm(request.POST, user=request.user)
        if form.is_valid():
            # Create a new schedule but don't save to DB yet
            schedule = form.save(commit=False)
            # Add the current user
            schedule.user = request.user
            # Save the schedule to DB
            schedule.save()
            
            # Trigger initial scan and transfer immediately after adding schedule
            from backup_app.scheduler import scan_and_transfer_files
            scan_and_transfer_files(schedule.id)
            
            messages.success(request, f'Schedule {schedule.name} has been added!')
            return redirect('schedule_list')
    else:
        form = ScheduleConfigForm(user=request.user)
    
    context = {
        'title': 'Add Schedule',
        'form': form,
    }
    
    return render(request, 'backup_app/schedule_form.html', context)

@login_required
def edit_schedule(request, schedule_id):
    """Edit an existing schedule configuration"""
    # Get the schedule or return 404
    schedule = get_object_or_404(ScheduleConfig, id=schedule_id, user=request.user)
    
    if request.method == 'POST':
        form = ScheduleConfigForm(request.POST, instance=schedule, user=request.user)
        if form.is_valid():
            # Save the updated schedule to DB
            form.save()
            
            messages.success(request, f'Schedule {schedule.name} has been updated!')
            return redirect('schedule_list')
    else:
        form = ScheduleConfigForm(instance=schedule, user=request.user)
    
    context = {
        'title': 'Edit Schedule',
        'form': form,
        'schedule': schedule,
    }
    
    return render(request, 'backup_app/schedule_form.html', context)

@login_required
def delete_schedule(request, schedule_id):
    """Delete a schedule configuration"""
    # Only allow POST requests
    if request.method != 'POST':
        return JsonResponse({'error': 'Method not allowed'}, status=405)
    
    # Get the schedule or return 404
    schedule = get_object_or_404(ScheduleConfig, id=schedule_id, user=request.user)
    
    # Delete the schedule
    schedule_name = schedule.name
    schedule.delete()
    
    return JsonResponse({'success': True, 'message': f'Schedule {schedule_name} has been deleted'})

@login_required
def toggle_schedule(request, schedule_id):
    """Enable or disable a schedule"""
    # Only allow POST requests
    if request.method != 'POST':
        return JsonResponse({'error': 'Method not allowed'}, status=405)
    
    # Get the schedule or return 404
    schedule = get_object_or_404(ScheduleConfig, id=schedule_id, user=request.user)
    
    # Toggle the enabled state
    schedule.enabled = not schedule.enabled
    schedule.save()
    
    # Trigger initial scan and transfer immediately after enabling schedule
    if schedule.enabled:
        from backup_app.scheduler import scan_and_transfer_files
        scan_and_transfer_files(schedule.id)
    
    status = 'enabled' if schedule.enabled else 'disabled'
    
    return JsonResponse({'success': True, 'message': f'Schedule {schedule.name} has been {status}', 'enabled': schedule.enabled})
