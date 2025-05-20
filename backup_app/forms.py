from django import forms
from django.contrib.auth.forms import UserCreationForm, AuthenticationForm
from django.contrib.auth.models import User
from .models import ServerConfig, ScheduleConfig

class LoginForm(AuthenticationForm):
    username = forms.CharField(
        widget=forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Enter username'})
    )
    password = forms.CharField(
        widget=forms.PasswordInput(attrs={'class': 'form-control', 'placeholder': 'Enter password'})
    )
    remember_me = forms.BooleanField(required=False, widget=forms.CheckboxInput(attrs={'class': 'form-check-input'}))

class RegisterForm(UserCreationForm):
    username = forms.CharField(
        widget=forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Enter username'}),
        min_length=3,
        max_length=64
    )
    email = forms.EmailField(
        widget=forms.EmailInput(attrs={'class': 'form-control', 'placeholder': 'Enter email'})
    )
    password1 = forms.CharField(
        widget=forms.PasswordInput(attrs={'class': 'form-control', 'placeholder': 'Enter password'}),
        min_length=8
    )
    password2 = forms.CharField(
        widget=forms.PasswordInput(attrs={'class': 'form-control', 'placeholder': 'Confirm password'})
    )
    
    class Meta:
        model = User
        fields = ('username', 'email', 'password1', 'password2')

class ServerConfigForm(forms.ModelForm):
    AUTH_CHOICES = [
        ('password', 'Password'),
        ('key', 'SSH Private Key')
    ]
    
    SERVER_TYPE_CHOICES = [
        ('source', 'Source Server (Cloud)'),
        ('destination', 'Destination Server (Private)')
    ]
    
    name = forms.CharField(
        widget=forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Server name'})
    )
    host = forms.CharField(
        widget=forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Hostname or IP address'})
    )
    port = forms.IntegerField(
        widget=forms.NumberInput(attrs={'class': 'form-control', 'placeholder': 'SFTP port'}),
        initial=22,
        min_value=1,
        max_value=65535
    )
    username = forms.CharField(
        widget=forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'SFTP username'})
    )
    auth_type = forms.ChoiceField(
        choices=AUTH_CHOICES,
        widget=forms.Select(attrs={'class': 'form-select', 'id': 'authType'})
    )
    password = forms.CharField(
        widget=forms.PasswordInput(attrs={'class': 'form-control', 'placeholder': 'SFTP password'}),
        required=False
    )
    private_key = forms.CharField(
        widget=forms.Textarea(attrs={'class': 'form-control', 'placeholder': 'Paste your SSH private key here', 'rows': 5}),
        required=False
    )
    remote_path = forms.CharField(
        widget=forms.TextInput(attrs={'class': 'form-control', 'placeholder': '/path/to/backup/folder'})
    )
    server_type = forms.ChoiceField(
        choices=SERVER_TYPE_CHOICES,
        widget=forms.Select(attrs={'class': 'form-select'})
    )
    
    class Meta:
        model = ServerConfig
        fields = ['name', 'host', 'port', 'username', 'password', 'private_key', 'remote_path', 'server_type']
        
    def clean(self):
        cleaned_data = super().clean()
        auth_type = cleaned_data.get('auth_type')
        password = cleaned_data.get('password')
        private_key = cleaned_data.get('private_key')
        
        if auth_type == 'password' and not password:
            self.add_error('password', 'Password is required when using password authentication')
            
        if auth_type == 'key' and not private_key:
            self.add_error('private_key', 'Private key is required when using key authentication')
            
        return cleaned_data

class ScheduleConfigForm(forms.ModelForm):
    FREQUENCY_CHOICES = [
        ('hourly', 'Every Hour'),
        ('daily', 'Every Day'),
        ('weekly', 'Every Week'),
        ('custom', 'Custom Schedule')
    ]
    
    name = forms.CharField(
        widget=forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Schedule name'})
    )
    source_server = forms.ModelChoiceField(
        queryset=ServerConfig.objects.filter(server_type='source'),
        widget=forms.Select(attrs={'class': 'form-select'}),
        empty_label='Select source server'
    )
    destination_server = forms.ModelChoiceField(
        queryset=ServerConfig.objects.filter(server_type='destination'),
        widget=forms.Select(attrs={'class': 'form-select'}),
        empty_label='Select destination server'
    )
    frequency = forms.ChoiceField(
        choices=FREQUENCY_CHOICES,
        widget=forms.Select(attrs={'class': 'form-select'})
    )
    cron_expression = forms.CharField(
        widget=forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Cron expression (e.g., */5 * * * *)'}),
        required=False
    )
    enabled = forms.BooleanField(
        initial=True,
        required=False,
        widget=forms.CheckboxInput(attrs={'class': 'form-check-input'})
    )
    
    class Meta:
        model = ScheduleConfig
        fields = ['name', 'source_server', 'destination_server', 'frequency', 'cron_expression', 'enabled']
        
    def __init__(self, *args, user=None, **kwargs):
        super().__init__(*args, **kwargs)
        if user:
            self.fields['source_server'].queryset = ServerConfig.objects.filter(user=user, server_type='source')
            self.fields['destination_server'].queryset = ServerConfig.objects.filter(user=user, server_type='destination')
    
    def clean(self):
        cleaned_data = super().clean()
        frequency = cleaned_data.get('frequency')
        cron_expression = cleaned_data.get('cron_expression')
        
        if frequency == 'custom' and not cron_expression:
            self.add_error('cron_expression', 'Cron expression is required for custom schedules')
            
        return cleaned_data
