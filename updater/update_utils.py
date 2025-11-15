"""
更新工具模块
提供通用的更新相关工具函数
"""

import json
import os
import datetime
import logging

# 获取项目根目录
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONFIG_PATH = os.path.join(PROJECT_ROOT, 'fileshare_config.json')
LOG_DIR = os.path.join(PROJECT_ROOT, 'log')
LOG_FILE = os.path.join(LOG_DIR, 'update.log')

# 确保日志目录存在
os.makedirs(LOG_DIR, exist_ok=True)

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler(LOG_FILE, encoding='utf-8'),
        logging.StreamHandler()
    ]
)

def get_current_version():
    """
    获取当前应用版本号
    
    Returns:
        str: 当前版本号，如果检测到exe环境则返回特殊标识
    """
    try:
        # 检查是否是exe环境（PyInstaller打包的可执行文件）
        is_exe = getattr(sys, 'frozen', False)
        
        if is_exe:
            # 如果是exe文件，不执行更新操作
            log_update('INFO', '检测到exe环境，禁用自动更新功能')
            return 'EXE_ENVIRONMENT'
        
        # 检查主文件扩展名
        main_file_path = sys.argv[0] if hasattr(sys, 'argv') and sys.argv else __file__
        if main_file_path:
            file_ext = os.path.splitext(main_file_path)[1].lower()
            if file_ext == '.exe':
                log_update('INFO', '检测到exe文件，禁用自动更新功能')
                return 'EXE_ENVIRONMENT'
        
        # 首先尝试从配置文件读取
        if os.path.exists(CONFIG_PATH):
            with open(CONFIG_PATH, 'r', encoding='utf-8') as f:
                config = json.load(f)
                version = config.get('app_version')
                if version:
                    return version
        
        # 如果配置文件没有版本信息，尝试从server.py读取
        server_path = os.path.join(PROJECT_ROOT, 'server.py')
        if os.path.exists(server_path):
            with open(server_path, 'r', encoding='utf-8') as f:
                content = f.read()
                # 查找app_version设置
                import re
                match = re.search(r"'app_version':\s*'([^']*)'", content)
                if match:
                    return match.group(1)
        
        # 如果都失败，返回默认版本
        return '0.0'
        
    except Exception as e:
        print(f"获取版本号时发生错误: {e}")
        return '0.0'

def log_update(level, message):
    """
    记录更新日志
    
    Args:
        level (str): 日志级别 ('INFO', 'WARNING', 'ERROR')
        message (str): 日志消息
    """
    try:
        # 根据级别选择日志方法
        if level.upper() == 'INFO':
            logging.info(message)
        elif level.upper() == 'WARNING':
            logging.warning(message)
        elif level.upper() == 'ERROR':
            logging.error(message)
        else:
            logging.info(message)
    except Exception as e:
        print(f"记录日志时发生错误: {e}")

def save_update_info(update_info):
    """
    保存更新信息到文件
    
    Args:
        update_info (dict): 更新信息字典
    """
    try:
        # 创建更新信息文件路径
        update_info_path = os.path.join(PROJECT_ROOT, 'update_info.json')
        
        # 添加保存时间
        update_info['saved_at'] = datetime.datetime.now().isoformat()
        
        # 保存到文件
        with open(update_info_path, 'w', encoding='utf-8') as f:
            json.dump(update_info, f, indent=4, ensure_ascii=False)
        
        log_update('INFO', f"更新信息已保存: {update_info_path}")
        return True
        
    except Exception as e:
        log_update('ERROR', f"保存更新信息失败: {e}")
        return False

def load_update_info():
    """
    加载更新信息
    
    Returns:
        dict or None: 更新信息字典，如果文件不存在或读取失败则返回None
    """
    try:
        update_info_path = os.path.join(PROJECT_ROOT, 'update_info.json')
        
        if not os.path.exists(update_info_path):
            return None
        
        with open(update_info_path, 'r', encoding='utf-8') as f:
            return json.load(f)
            
    except Exception as e:
        log_update('ERROR', f"加载更新信息失败: {e}")
        return None

def clear_update_info():
    """
    清除更新信息文件
    """
    try:
        update_info_path = os.path.join(PROJECT_ROOT, 'update_info.json')
        
        if os.path.exists(update_info_path):
            os.remove(update_info_path)
            log_update('INFO', "更新信息已清除")
            
    except Exception as e:
        log_update('ERROR', f"清除更新信息失败: {e}")

def format_file_size(size_bytes):
    """
    格式化文件大小
    
    Args:
        size_bytes (int): 字节数
    
    Returns:
        str: 格式化后的大小字符串
    """
    if size_bytes == 0:
        return "0 B"
    
    size_names = ["B", "KB", "MB", "GB", "TB"]
    i = 0
    while size_bytes >= 1024 and i < len(size_names) - 1:
        size_bytes /= 1024.0
        i += 1
    
    return f"{size_bytes:.1f} {size_names[i]}"

def validate_update_package(update_file_path):
    """
    验证更新包的完整性
    
    Args:
        update_file_path (str): 更新包文件路径
    
    Returns:
        bool: 是否验证通过
    """
    try:
        if not os.path.exists(update_file_path):
            return False
        
        # 检查文件大小（至少要有内容）
        file_size = os.path.getsize(update_file_path)
        if file_size < 1024:  # 小于1KB可能不是有效的更新包
            log_update('WARNING', f"更新包文件可能过小: {file_size} bytes")
            return False
        
        # 检查文件扩展名
        valid_extensions = ['.zip', '.exe', '.tar.gz', '.tar', '.gz']
        file_ext = os.path.splitext(update_file_path)[1].lower()
        
        if file_ext not in valid_extensions:
            log_update('WARNING', f"不支持的更新包格式: {file_ext}")
            return False
        
        log_update('INFO', f"更新包验证通过: {update_file_path} ({format_file_size(file_size)})")
        return True
        
    except Exception as e:
        log_update('ERROR', f"验证更新包时发生错误: {e}")
        return False

def cleanup_old_updates():
    """
    清理过期的更新文件
    
    Args:
        days (int): 保留最近N天的更新文件
    """
    try:
        import glob
        
        # 获取更新目录
        from .update_download import UPDATE_DIR
        
        if not os.path.exists(UPDATE_DIR):
            return
        
        # 计算过期时间（7天前）
        cutoff_time = datetime.datetime.now() - datetime.timedelta(days=7)
        
        # 清理下载目录
        download_dir = os.path.join(UPDATE_DIR, 'download')
        if os.path.exists(download_dir):
            for file_path in glob.glob(os.path.join(download_dir, '*')):
                if os.path.getmtime(file_path) < cutoff_time.timestamp():
                    os.remove(file_path)
                    log_update('INFO', f"已清理过期更新文件: {file_path}")
        
        # 清理备份目录中过期的备份（保留最近3个）
        backup_dir = os.path.join(UPDATE_DIR, 'backup')
        if os.path.exists(backup_dir):
            backup_dirs = [d for d in os.listdir(backup_dir) if os.path.isdir(os.path.join(backup_dir, d))]
            backup_dirs.sort(key=lambda x: os.path.getmtime(os.path.join(backup_dir, x)), reverse=True)
            
            # 删除除了最近的3个以外的所有备份
            for old_backup in backup_dirs[3:]:
                old_backup_path = os.path.join(backup_dir, old_backup)
                shutil.rmtree(old_backup_path)
                log_update('INFO', f"已清理过期备份: {old_backup_path}")
                
    except Exception as e:
        log_update('ERROR', f"清理过期更新时发生错误: {e}")

# 添加缺少的导入
try:
    import shutil
except ImportError:
    pass