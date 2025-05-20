from django.urls import path
from .views import auth_views, dashboard_views, config_views, transfer_views

urlpatterns = [
    # Authentication URLs
    path('login/', auth_views.login_view, name='login'),
    path('register/', auth_views.register_view, name='register'),
    path('logout/', auth_views.logout_view, name='logout'),
    
    # Dashboard URLs
    path('', dashboard_views.dashboard, name='dashboard'),
    path('files/', dashboard_views.file_list, name='file_list'),
    path('files/<int:file_id>/', dashboard_views.file_detail, name='file_detail'),
    path('files/<int:file_id>/transfer/', dashboard_views.initiate_transfer, name='initiate_transfer'),
    path('files/<int:file_id>/cancel/', dashboard_views.cancel_transfer, name='cancel_transfer'),
    
    # Server Configuration URLs
    path('servers/', config_views.server_list, name='server_list'),
    path('servers/add/', config_views.add_server, name='add_server'),
    path('servers/<int:server_id>/edit/', config_views.edit_server, name='edit_server'),
    path('servers/<int:server_id>/delete/', config_views.delete_server, name='delete_server'),
    path('servers/<int:server_id>/test/', config_views.test_server_connection, name='test_server_connection'),
    
    # Schedule Configuration URLs
    path('schedules/', config_views.schedule_list, name='schedule_list'),
    path('schedules/add/', config_views.add_schedule, name='add_schedule'),
    path('schedules/<int:schedule_id>/edit/', config_views.edit_schedule, name='edit_schedule'),
    path('schedules/<int:schedule_id>/delete/', config_views.delete_schedule, name='delete_schedule'),
    path('schedules/<int:schedule_id>/toggle/', config_views.toggle_schedule, name='toggle_schedule'),
    
    # Transfer URLs
    path('scan/', transfer_views.scan_files, name='scan_files'),
    path('transfer/all/', transfer_views.initiate_transfer_all, name='initiate_transfer_all'),
    path('transfer/<int:file_id>/process/', transfer_views.process_transfer, name='process_transfer'),
    path('retry/', transfer_views.retry_failed, name='retry_failed'),
]