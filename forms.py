from flask_wtf import FlaskForm
from wtforms import StringField, PasswordField, BooleanField, SubmitField, SelectField, IntegerField, TextAreaField
from wtforms.validators import DataRequired, Email, EqualTo, Length, ValidationError, NumberRange, Optional

class LoginForm(FlaskForm):
    """Form for user login"""
    username = StringField('Username', validators=[DataRequired()])
    password = PasswordField('Password', validators=[DataRequired()])
    remember = BooleanField('Remember Me')
    submit = SubmitField('Login')

class RegisterForm(FlaskForm):
    """Form for user registration"""
    username = StringField('Username', validators=[DataRequired(), Length(min=3, max=64)])
    email = StringField('Email', validators=[DataRequired(), Email()])
    password = PasswordField('Password', validators=[
        DataRequired(),
        Length(min=8, message="Password must be at least 8 characters")
    ])
    confirm = PasswordField('Confirm Password', validators=[
        DataRequired(),
        EqualTo('password', message="Passwords must match")
    ])
    submit = SubmitField('Register')

class ServerConfigForm(FlaskForm):
    """Form for adding/editing server configurations"""
    name = StringField('Server Name', validators=[DataRequired(), Length(max=64)])
    host = StringField('Hostname/IP', validators=[DataRequired(), Length(max=120)])
    port = IntegerField('Port', validators=[DataRequired(), NumberRange(min=1, max=65535)], default=22)
    username = StringField('Username', validators=[DataRequired(), Length(max=64)])
    
    auth_type = SelectField('Authentication Method', choices=[
        ('password', 'Password'),
        ('key', 'SSH Private Key')
    ])
    
    password = PasswordField('Password', validators=[Optional(), Length(max=256)])
    private_key = TextAreaField('Private Key', validators=[Optional(), Length(max=10000)])
    
    remote_path = StringField('Remote Directory Path', validators=[DataRequired(), Length(max=256)])
    
    server_type = SelectField('Server Type', choices=[
        ('source', 'Source Server (Cloud)'),
        ('destination', 'Destination Server (Private)')
    ])
    
    submit = SubmitField('Save Server')
    
    def validate(self):
        """Custom validation to ensure either password or private key is provided"""
        if not super().validate():
            return False
            
        if self.auth_type.data == 'password' and not self.password.data:
            self.password.errors.append('Password is required when using password authentication')
            return False
            
        if self.auth_type.data == 'key' and not self.private_key.data:
            self.private_key.errors.append('Private key is required when using key authentication')
            return False
            
        return True

class ScheduleConfigForm(FlaskForm):
    """Form for configuring backup schedules"""
    name = StringField('Schedule Name', validators=[DataRequired(), Length(max=64)])
    
    source_server_id = SelectField('Source Server', validators=[DataRequired()], coerce=int)
    destination_server_id = SelectField('Destination Server', validators=[DataRequired()], coerce=int)
    
    frequency = SelectField('Frequency', choices=[
        ('hourly', 'Every Hour'),
        ('daily', 'Every Day'),
        ('weekly', 'Every Week'),
        ('custom', 'Custom Schedule')
    ])
    
    cron_expression = StringField('Cron Expression', validators=[Optional(), Length(max=64)])
    enabled = BooleanField('Enabled', default=True)
    
    submit = SubmitField('Save Schedule')
    
    def validate(self):
        """Custom validation to ensure cron expression is provided for custom schedules"""
        if not super().validate():
            return False
            
        if self.frequency.data == 'custom' and not self.cron_expression.data:
            self.cron_expression.errors.append('Cron expression is required for custom schedules')
            return False
            
        return True
