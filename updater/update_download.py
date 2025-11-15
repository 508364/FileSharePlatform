"""
更新下载模块
负责下载并应用系统更新
"""

import requests
import os
import shutil
import json
from pathlib import Path
import hashlib

# 更新文件存储目录
UPDATE_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'updates')
# 备份目录
BACKUP_DIR = os.path.join(UPDATE_DIR, 'backup')
# 更新下载目录
DOWNLOAD_DIR = os.path.join(UPDATE_DIR, 'download')

# 创建必要的目录
os.makedirs(UPDATE_DIR, exist_ok=True)
os.makedirs(BACKUP_DIR, exist_ok=True)
os.makedirs(DOWNLOAD_DIR, exist_ok=True)

def download_update(download_url, version, callback=None):
    """
    下载更新文件
    
    Args:
        download_url (str): 下载链接
        version (str): 新版本号
        callback (callable, optional): 下载进度回调函数
    
    Returns:
        str: 下载的文件路径，如果失败返回None
    """
    try:
        # 获取文件名
        filename = download_url.split('/')[-1]
        # 确保文件名安全
        filename = filename.split('?')[0]  # 移除查询参数
        
        # 创建保存路径
        save_path = os.path.join(DOWNLOAD_DIR, filename)
        
        # 下载文件
        print(f"开始下载更新文件: {filename}")
        
        response = requests.get(download_url, stream=True)
        response.raise_for_status()
        
        total_size = int(response.headers.get('content-length', 0))
        downloaded_size = 0
        
        with open(save_path, 'wb') as f:
            for chunk in response.iter_content(chunk_size=8192):
                if chunk:
                    f.write(chunk)
                    downloaded_size += len(chunk)
                    
                    # 调用进度回调
                    if callback:
                        progress = (downloaded_size / total_size) * 100 if total_size > 0 else 0
                        callback(progress)
        
        # 验证文件（如果服务器提供了哈希值）
        # 注意: GitHub API不直接提供文件哈希，这里只是一个示例
        # 实际项目中可能需要从其他地方获取哈希值
        
        print(f"更新文件下载完成: {save_path}")
        return save_path
        
    except requests.exceptions.RequestException as e:
        print(f"下载失败: {e}")
        return None
    except Exception as e:
        print(f"下载更新时发生错误: {e}")
        return None

def backup_current_files():
    """
    备份当前系统文件
    
    Returns:
        bool: 备份是否成功
    """
    try:
        # 确定要备份的文件和目录
        files_to_backup = [
            os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'server.py'),
            os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'templates'),
            os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'static'),
        ]
        
        # 创建备份目录（使用时间戳）
        import time
        timestamp = time.strftime("%Y%m%d_%H%M%S")
        backup_path = os.path.join(BACKUP_DIR, f"backup_{timestamp}")
        os.makedirs(backup_path, exist_ok=True)
        
        # 备份文件
        for file_path in files_to_backup:
            if os.path.exists(file_path):
                if os.path.isdir(file_path):
                    shutil.copytree(file_path, os.path.join(backup_path, os.path.basename(file_path)))
                else:
                    shutil.copy2(file_path, backup_path)
        
        # 备份配置文件
        config_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'fileshare_config.json')
        if os.path.exists(config_path):
            shutil.copy2(config_path, backup_path)
        
        print(f"系统文件备份完成: {backup_path}")
        return True
        
    except Exception as e:
        print(f"备份失败: {e}")
        return False

def apply_update(update_file_path, version, callback=None):
    """
    应用更新
    
    Args:
        update_file_path (str): 更新文件路径
        version (str): 新版本号
        callback (callable, optional): 应用进度回调函数
    
    Returns:
        bool: 更新是否成功
    """
    try:
        if not os.path.exists(update_file_path):
            print(f"更新文件不存在: {update_file_path}")
            return False
        
        # 备份当前文件
        print("备份当前系统文件...")
        if not backup_current_files():
            print("备份失败，无法继续更新")
            return False
        
        # 确定解压目录
        extract_dir = os.path.join(UPDATE_DIR, f"extract_{version}")
        os.makedirs(extract_dir, exist_ok=True)
        
        # 解压文件
        print(f"解压更新文件...")
        if update_file_path.endswith('.zip'):
            import zipfile
            with zipfile.ZipFile(update_file_path, 'r') as zip_ref:
                zip_ref.extractall(extract_dir)
        elif update_file_path.endswith('.exe'):
            # 对于exe文件，我们只是记录它，稍后可能需要特殊处理
            print("检测到exe更新文件，需要手动安装")
            shutil.copy2(update_file_path, extract_dir)
        
        # 复制文件到系统目录
        print("应用更新文件...")
        base_dir = os.path.dirname(os.path.abspath(__file__))
        parent_dir = os.path.dirname(base_dir)
        
        for item in os.listdir(extract_dir):
            src = os.path.join(extract_dir, item)
            dst = os.path.join(parent_dir, item)
            
            if os.path.isdir(src):
                if os.path.exists(dst):
                    shutil.rmtree(dst)
                shutil.copytree(src, dst)
            else:
                shutil.copy2(src, dst)
        
        # 更新版本信息
        config_path = os.path.join(parent_dir, 'fileshare_config.json')
        if os.path.exists(config_path):
            with open(config_path, 'r', encoding='utf-8') as f:
                config = json.load(f)
            config['app_version'] = version
            with open(config_path, 'w', encoding='utf-8') as f:
                json.dump(config, f, indent=4, ensure_ascii=False)
        
        print(f"更新已成功应用至版本 {version}")
        return True
        
    except Exception as e:
        print(f"应用更新时发生错误: {e}")
        return False