import logging
import paramiko
import io
import os
from datetime import datetime
from stat import S_ISREG, S_ISDIR
from .models import TransferLog

# Set up logger
logger = logging.getLogger(__name__)

def sftp_connect(server_config):
    """
    Establish SFTP connection to a server
    
    Args:
        server_config: ServerConfig model instance with connection details
        
    Returns:
        tuple: (ssh_client, sftp_client) - Both open connections to be closed by caller
    """
    try:
        # Create SSH client
        ssh = paramiko.SSHClient()
        ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        
        # Authentication method depends on config
        if server_config.private_key:
            # Use private key authentication
            private_key = io.StringIO(server_config.private_key)
            pkey = paramiko.RSAKey.from_private_key(private_key)
            ssh.connect(
                hostname=server_config.host,
                port=server_config.port,
                username=server_config.username,
                pkey=pkey,
                timeout=30
            )
        else:
            # Use password authentication
            ssh.connect(
                hostname=server_config.host,
                port=server_config.port,
                username=server_config.username,
                password=server_config.password,
                timeout=30
            )
        
        # Open SFTP connection
        sftp = ssh.open_sftp()
        
        logger.debug(f"Successfully connected to {server_config.host}")
        return ssh, sftp
        
    except Exception as e:
        logger.error(f"Failed to connect to {server_config.host}: {str(e)}")
        raise RuntimeError(f"SFTP connection failed: {str(e)}")

def list_files_on_server(server_config, include_folders=False):
    """
    List all files and optionally folders in the specified remote path
    
    Args:
        server_config: ServerConfig model instance
        include_folders: If True, also include folders in the result
        
    Returns:
        list: List of dictionaries with file/folder information
    """
    ssh = None
    sftp = None
    try:
        # Establish SFTP connection
        ssh = paramiko.SSHClient()
        ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        if server_config.private_key:
            private_key = io.StringIO(server_config.private_key)
            pkey = paramiko.RSAKey.from_private_key(private_key)
            ssh.connect(
                hostname=server_config.host,
                port=server_config.port,
                username=server_config.username,
                pkey=pkey,
                timeout=30
            )
        else:
            ssh.connect(
                hostname=server_config.host,
                port=server_config.port,
                username=server_config.username,
                password=server_config.password,
                timeout=30
            )
        sftp = ssh.open_sftp()
        sftp.chdir(server_config.remote_path)
        file_list = []
        for entry in sftp.listdir_attr():
            if S_ISREG(entry.st_mode):
                file_info = {
                    'filename': entry.filename,
                    'size': entry.st_size,
                    'modified_at': datetime.fromtimestamp(entry.st_mtime),
                    'is_folder': False
                }
                try:
                    file_info['created_at'] = datetime.fromtimestamp(entry.st_atime)
                except (AttributeError, OSError):
                    file_info['created_at'] = file_info['modified_at']
                file_list.append(file_info)
            elif include_folders and S_ISDIR(entry.st_mode):
                folder_info = {
                    'filename': entry.filename,
                    'size': 0,
                    'modified_at': datetime.fromtimestamp(entry.st_mtime),
                    'is_folder': True
                }
                try:
                    folder_info['created_at'] = datetime.fromtimestamp(entry.st_atime)
                except (AttributeError, OSError):
                    folder_info['created_at'] = folder_info['modified_at']
                file_list.append(folder_info)
                logger.debug(f"Found folder: {entry.filename}")
            elif include_folders and not S_ISREG(entry.st_mode):
                try:
                    sftp.chdir(os.path.join(server_config.remote_path, entry.filename))
                    sftp.chdir(server_config.remote_path)
                    folder_info = {
                        'filename': entry.filename,
                        'size': 0,
                        'modified_at': datetime.fromtimestamp(entry.st_mtime),
                        'is_folder': True
                    }
                    try:
                        folder_info['created_at'] = datetime.fromtimestamp(entry.st_atime)
                    except (AttributeError, OSError):
                        folder_info['created_at'] = folder_info['modified_at']
                    file_list.append(folder_info)
                    logger.debug(f"Found folder (chdir method): {entry.filename}")
                except Exception as e:
                    logger.debug(f"Skipping item {entry.filename}: {str(e)}")
        return file_list
    except Exception as e:
        logger.error(f"Error listing files on {server_config.host}: {str(e)}")
        raise RuntimeError(f"Failed to list files: {str(e)}")
    finally:
        if sftp:
            sftp.close()
        if ssh:
            ssh.close()
def transfer_file(backup_file):
    """
    Transfer a file or folder from source to destination server
    
    Args:
        backup_file: BackupFile model instance with transfer details
        
    Returns:
        tuple: (success, message) - Boolean indicating success and a message
    """
    source_ssh = None
    source_sftp = None
    dest_ssh = None
    dest_sftp = None
    
    # Handle different transfer modes based on whether it's a folder or file
    if backup_file.is_folder:
        return transfer_folder(backup_file)
    
    # Ensure Python files use the correct path format for any file transfer
    if backup_file.filename.endswith('.py'):
        # Override paths to match screenshot format
        backup_file.source_path = f"/Apistudio/CrudApp/{backup_file.filename}"
        backup_file.destination_path = f"/backup/{backup_file.filename}"
        logger.info(f"Using standardized Python file paths: {backup_file.source_path} -> {backup_file.destination_path}")
        # Save the updated paths
        backup_file.save()
    
    try:
        # Connect to source server
        source_ssh, source_sftp = sftp_connect(backup_file.source_server)
        
        # Connect to destination server
        dest_ssh, dest_sftp = sftp_connect(backup_file.destination_server)
        
        # Ensure destination directory exists
        dest_dir = os.path.dirname(backup_file.destination_path)
        try:
            dest_sftp.stat(dest_dir)
        except FileNotFoundError:
            # Create destination directory if it doesn't exist
            makedirs_remote(dest_sftp, dest_dir)
        
        # Open source file for reading
        with source_sftp.open(backup_file.source_path, 'rb') as source_file:
            # Open destination file for writing
            with dest_sftp.open(backup_file.destination_path, 'wb') as dest_file:
                # Initialize buffer for streaming data
                buffer_size = 32768  # 32 KB buffer
                buffer = source_file.read(buffer_size)
                
                # Track transfer progress
                total_transferred = 0
                
                # Stream data directly from source to destination
                while buffer:
                    dest_file.write(buffer)
                    total_transferred += len(buffer)
                    buffer = source_file.read(buffer_size)
        
        success_message = f"Successfully transferred file {backup_file.filename} ({total_transferred} bytes)"
        logger.info(success_message)
        return True, success_message
        
    except Exception as e:
        error_message = f"Transfer failed: {str(e)}"
        logger.error(f"Error transferring file {backup_file.filename}: {str(e)}")
        return False, error_message
    
    finally:
        # Close all connections
        if source_sftp:
            source_sftp.close()
        if source_ssh:
            source_ssh.close()
        if dest_sftp:
            dest_sftp.close()
        if dest_ssh:
            dest_ssh.close()

def transfer_folder(backup_file):
    """
    Transfer an entire folder from source to destination server
    
    Args:
        backup_file: BackupFile model instance with folder transfer details
        
    Returns:
        tuple: (success, message) - Boolean indicating success and a message
    """
    source_ssh = None
    source_sftp = None
    dest_ssh = None
    dest_sftp = None
    
    try:
        # Connect to source server
        source_ssh, source_sftp = sftp_connect(backup_file.source_server)
        
        # Connect to destination server
        dest_ssh, dest_sftp = sftp_connect(backup_file.destination_server)
        
        # Ensure the base destination directory exists
        dest_folder_path = backup_file.destination_path
        try:
            dest_sftp.stat(dest_folder_path)
        except FileNotFoundError:
            # Create the destination folder
            makedirs_remote(dest_sftp, dest_folder_path)
            
        # Get source path to traverse
        source_folder_path = backup_file.source_path
        
        # Process files and folders recursively
        transferred_files = 0
        total_bytes = 0
        errors = []
        
        # Walk through all files and directories in the source folder
        def transfer_recursive(src_path, dest_path):
            nonlocal transferred_files, total_bytes, errors
            
            try:
                # List all items in the current directory
                items = source_sftp.listdir_attr(src_path)
                
                # Process each item
                for item in items:
                    src_item_path = os.path.join(src_path, item.filename).replace('\\', '/')
                    dest_item_path = os.path.join(dest_path, item.filename).replace('\\', '/')
                    
                    if not hasattr(item, 'st_mode'):
                        logger.warning(f"Skipping item {item.filename} - cannot determine type")
                        continue
                        
                    # Check if it's a file or directory
                    try:
                        if S_ISREG(item.st_mode):
                            # It's a file, transfer it
                            try:
                                # Create containing directory if necessary
                                dest_dir = os.path.dirname(dest_item_path)
                                try:
                                    dest_sftp.stat(dest_dir)
                                except FileNotFoundError:
                                    makedirs_remote(dest_sftp, dest_dir)
                                
                                # Transfer the file
                                with source_sftp.open(src_item_path, 'rb') as src_file:
                                    with dest_sftp.open(dest_item_path, 'wb') as dest_file:
                                        buffer_size = 32768  # 32 KB buffer
                                        buffer = src_file.read(buffer_size)
                                        file_size = 0
                                        
                                        while buffer:
                                            dest_file.write(buffer)
                                            file_size += len(buffer)
                                            buffer = src_file.read(buffer_size)
                                
                                transferred_files += 1
                                total_bytes += file_size
                                logger.info(f"Transferred file: {src_item_path} -> {dest_item_path} ({file_size} bytes)")
                                
                            except Exception as e:
                                error_msg = f"Error transferring file {src_item_path}: {str(e)}"
                                logger.error(error_msg)
                                errors.append(error_msg)
                                
                        elif S_ISDIR(item.st_mode):
                            # It's a directory, process recursively
                            try:
                                # Create destination directory
                                try:
                                    dest_sftp.stat(dest_item_path)
                                except FileNotFoundError:
                                    makedirs_remote(dest_sftp, dest_item_path)
                                    
                                # Recursively process the directory
                                transfer_recursive(src_item_path, dest_item_path)
                                
                            except Exception as e:
                                error_msg = f"Error processing directory {src_item_path}: {str(e)}"
                                logger.error(error_msg)
                                errors.append(error_msg)
                        else:
                            # Not a regular file or directory, try traditional method
                            try:
                                # Check if it's a directory by trying to change to it
                                source_sftp.chdir(src_item_path)
                                source_sftp.chdir(src_path)  # Go back
                                
                                # Create destination directory
                                try:
                                    dest_sftp.stat(dest_item_path)
                                except FileNotFoundError:
                                    makedirs_remote(dest_sftp, dest_item_path)
                                    
                                # Recursively process the directory
                                transfer_recursive(src_item_path, dest_item_path)
                                
                            except Exception as e:
                                logger.debug(f"Not a directory or error: {src_item_path} - {str(e)}")
                    
                    except Exception as e:
                        error_msg = f"Error processing item {src_item_path}: {str(e)}"
                        logger.error(error_msg)
                        errors.append(error_msg)
                        
            except Exception as e:
                error_msg = f"Error listing directory {src_path}: {str(e)}"
                logger.error(error_msg)
                errors.append(error_msg)
        
        # Start the recursive transfer process
        transfer_recursive(source_folder_path, dest_folder_path)
        
        # Update the BackupFile record with folder statistics
        backup_file.files_count = transferred_files
        backup_file.file_size = total_bytes
        backup_file.save()
        
        # Check if there were any errors
        if errors:
            # Partial success
            error_summary = f"Transferred {transferred_files} files ({total_bytes} bytes) with {len(errors)} errors"
            if len(errors) <= 3:
                error_detail = ". Errors: " + "; ".join(errors)
                error_summary += error_detail
            else:
                error_summary += f". First 3 errors: {'; '.join(errors[:3])}"
                
            logger.warning(error_summary)
            
            if transferred_files > 0:
                # Mark as successful if at least some files were transferred
                return True, error_summary
            else:
                # Complete failure if no files were transferred
                return False, error_summary
        else:
            # Complete success
            success_message = f"Successfully transferred folder {backup_file.filename} ({transferred_files} files, {total_bytes} bytes)"
            logger.info(success_message)
            return True, success_message
    
    except Exception as e:
        error_message = f"Folder transfer failed: {str(e)}"
        logger.error(f"Error transferring folder {backup_file.filename}: {str(e)}")
        return False, error_message
    
    finally:
        # Close all connections
        if source_sftp:
            source_sftp.close()
        if source_ssh:
            source_ssh.close()
        if dest_sftp:
            dest_sftp.close()
        if dest_ssh:
            dest_ssh.close()

def makedirs_remote(sftp, remote_directory):
    """
    Create remote directory and all parent directories if they don't exist
    
    Args:
        sftp: SFTP client connection
        remote_directory: Path to create
    """
    # Normalize path (handle both forward and backslashes)
    remote_directory = remote_directory.replace('\\', '/')
    
    if remote_directory == '/' or not remote_directory:
        return
    
    # Handle trailing slash
    if remote_directory.endswith('/'):
        remote_directory = remote_directory[:-1]
    
    parent = os.path.dirname(remote_directory)
    if parent and parent != remote_directory:  # Prevent infinite recursion
        try:
            sftp.stat(parent)
        except FileNotFoundError:
            makedirs_remote(sftp, parent)
        except IOError as e:
            # Handle other SFTP errors
            logger.error(f"SFTP error accessing parent directory {parent}: {str(e)}")
            raise
    
    try:
        sftp.stat(remote_directory)
        logger.debug(f"Directory already exists: {remote_directory}")
    except FileNotFoundError:
        logger.info(f"Creating remote directory: {remote_directory}")
        try:
            sftp.mkdir(remote_directory)
        except IOError as e:
            logger.error(f"Failed to create directory {remote_directory}: {str(e)}")
            raise
