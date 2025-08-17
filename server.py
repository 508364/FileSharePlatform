#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
文件共享平台服务器端主程序

该程序实现了一个基于Flask的文件共享平台,提供文件上传、下载、管理功能,
以及系统资源监控、GitHub仓库克隆等辅助功能。
"""

# ==============================================
# 标准库导入
# ==============================================
import os
import sys
import shutil
import time
import json
import functools
import psutil
import socket
import netifaces
import threading
import requests
import queue
import hashlib
import tempfile
import concurrent
import concurrent.futures
import math
import uuid
import urllib.error
import urllib.parse
import urllib.request
import subprocess
import platform
import zipfile
from datetime import datetime, timedelta
import re
import hmac


# ==============================================
# 第三方库导入
# ==============================================
from werkzeug.utils import secure_filename
from urllib.parse import urlparse
from urllib3.util.retry import Retry
from requests import Session
from requests.adapters import HTTPAdapter
from flask import Flask, render_template, send_from_directory, request, jsonify, abort, session, redirect, url_for, flash

# PyPDF库导入
try:
    import pypdf
except ImportError:
    print("PyPDF库未安装,请运行 'pip install PyPDF' 安装")
    PyPDF = None

# 确保JSONDecodeError可用
try:
    from json import JSONDecodeError
except ImportError:
    from requests.exceptions import JSONDecodeError

# 确保json模块有JSONDecodeError属性
if not hasattr(json, 'JSONDecodeError'):
    json.JSONDecodeError = JSONDecodeError

# ==============================================
# 全局变量与配置
# ==============================================

# Flask应用实例
app = Flask(__name__)
app.secret_key = os.urandom(24)  # 添加密钥用于session管理

# 线程锁 - 用于确保文件操作的线程安全
upload_lock = threading.Lock()

# GitHub镜像克隆队列及相关状态管理
github_clone_queue = queue.Queue()
github_clone_tasks = {}
github_clone_lock = threading.Lock()
active_cloners = {}  # 当前活跃的克隆任务

# 离线下载任务存储
OFFLINE_TASKS = {}
OFFLINE_QUEUE = queue.Queue()

# 系统配置默认值
DEFAULT_CONFIG = {
    'upload_folder': 'uploads',        # 文件上传目录
    'max_file_size': 100,              # 单个文件最大大小(MB)
    'max_total_size': 1024,            # 总存储空间大小(MB)
    'app_name': '文件共享平台',         # 应用名称
    'app_version': '1.7',              # 应用版本
    'admin_user': 'admin',             # 管理员用户名
    'admin_password': 'admin@123',     # 管理员密码
    'port': 5000,                      # 服务端口
    'network_interface': 'auto',       # 网络接口配置
    'geetest_id': '',                  # 极验验证ID
    'geetest_key': '',                 # 极验验证密钥
    'offline_download_enabled': True   # 是否启用离线下载
}

# 系统当前配置 - 初始化为默认配置的副本
system_config = DEFAULT_CONFIG.copy()

# ===============================================
# 更新检查功能
# ===============================================

def check_for_updates(current_version):
    """
    检查GitHub上是否有新版本
    
    Args:
        current_version (str): 当前应用版本
    
    Returns:
        dict: 包含更新信息的字典,如果没有更新则返回None
    """
    try:
        # GitHub仓库信息
        owner = '508364'
        repo = 'FileSharePlatform'
        api_url = f'https://api.github.com/repos/{owner}/{repo}/releases/latest'
        
        # 发送请求
        session = requests.Session()
        retry = Retry(total=3, backoff_factor=0.5)
        adapter = HTTPAdapter(max_retries=retry)
        session.mount('https://', adapter)
        
        response = session.get(api_url, timeout=10)
        response.raise_for_status()
        
        # 解析响应
        release_info = response.json()
        latest_version = release_info.get('tag_name', '').replace('FileSharePlatform-v', '')
        
        # 版本比较
        if latest_version and latest_version > current_version:
            # 构建下载链接
            download_url = f'https://github.com/{owner}/{repo}/releases/tag/FileSharePlatform-v{latest_version}'
            
            return {
                'current_version': current_version,
                'latest_version': latest_version,
                'download_url': download_url,
                'release_notes': release_info.get('body', '')
            }
        return None
    except Exception as e:
        print(f"检查更新失败: {e}")
        return None

# 配置与元数据文件路径
CONFIG_FILE = 'fileshare_config.json'   # 系统配置文件
METADATA_FILE = 'files_metadata.json'   # 文件元数据存储文件

# 服务启动时间
SERVICE_START_TIME = datetime.now()

# ==============================================
# 系统初始化与配置管理
# ==============================================

def init_system():
    """
    初始化系统环境
    
    创建必要目录、加载保存配置并确保元数据文件有效
    """
    
    # 创建必要目录 - 使用绝对路径确保打包后能正确访问
    # 确保upload_folder是绝对路径
    if not os.path.isabs(system_config['upload_folder']):
        system_config['upload_folder'] = os.path.abspath(system_config['upload_folder'])
    
    if not os.path.exists(system_config['upload_folder']):
        os.makedirs(system_config['upload_folder'])
    
    # 加载保存的配置
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, 'r', encoding='utf_8') as f:
                saved_config = json.load(f)
                for key in saved_config:
                    if key in system_config:
                        system_config[key] = saved_config[key]
        except Exception as e:
            print(f"配置加载错误: {e}")
    
    # 确保元数据文件有效
    if not os.path.exists(METADATA_FILE):
        with open(METADATA_FILE, 'w', encoding='utf_8') as f:
            json.dump({}, f)
    
    # 修复空文件问题
    elif os.path.getsize(METADATA_FILE) == 0:
        with open(METADATA_FILE, 'w', encoding='utf_8') as f:
            json.dump({}, f)
    
    print("系统初始化完成,元数据文件已就绪")


def save_config():
    """保存当前配置到配置文件"""
    try:
        with open(CONFIG_FILE,'w', encoding='utf_8') as f:  # 使用utf_8编码保存
            json.dump(system_config,f,indent=4,ensure_ascii=False)
    except Exception as e:
        print(f"配置保存失败: {e}")

# ==============================================
# 文件元数据管理
# ==============================================

# 用于记录文件下载时间的字典，防止多线程下载时重复计数
# 格式: {filename: last_download_time}
download_time_records = {}
# 下载去重时间窗口（秒）
DOWNLOAD_DEDUPE_WINDOW = 1

def load_metadata():
    """
    加载文件元数据
    
    如果文件不存在或为空,创建有效的JSON文件;
    如果文件格式错误,尝试重置为有效JSON
    
    Returns:
        dict: 包含文件元数据的字典
    """
    # 如果文件不存在或为空,创建有效的JSON文件
    if not os.path.exists(METADATA_FILE) or os.path.getsize(METADATA_FILE) == 0:
        try:
            with open(METADATA_FILE, 'w', encoding='utf_8') as f:
                json.dump({}, f)  # 创建有效的空JSON
            return {}
        except Exception as e:
            print(f"元数据文件创建失败:.{e}")
            return {}
    
    try:
        with open(METADATA_FILE, 'r', encoding='utf_8') as f:
            return json.load(f)
    except json.JSONDecodeError:
        print("元数据文件格式错误,重置中...")
        try:
            with open(METADATA_FILE, 'w', encoding='utf_8') as f:
                json.dump({}, f)  # 重置为有效JSON
            return {}
        except Exception as e:
            print(f"元数据重置失败: {e}")
            return {}
    except Exception as e:
        print(f"元数据加载错误: {e}")
        return {}


def update_metadata(filename, action='upload'):
    """
    更新文件元数据
    
    Args:
        filename (str): 文件名
        action (str): 操作类型,可选值: 'upload' | 'download' | 'delete'
    
    Returns:
        dict or None: 更新后的文件元数据,如文件不存在则返回None
    """
    metadata = load_metadata()
    file_path = os.path.join(system_config['upload_folder'], filename)
    
    if not os.path.exists(file_path) and action != 'delete':
        return None
    
    # 获取文件属性
    if action != 'delete':
        stat = os.stat(file_path)
        file_size = stat.st_size
        file_mtime = stat.st_mtime
        file_ctime = stat.st_ctime
    
    # 初始化文件元数据
    if filename not in metadata and action != 'delete':
        metadata[filename] = {
            'size': file_size,
            'created': file_ctime,
            'modified': file_mtime,
            'download_count': 0
        }
    
    # 更新元数据
    if action == 'download':
        # 检查是否在去重时间窗口内
        current_time = time.time()
        last_download_time = download_time_records.get(filename, 0)
        
        # 如果不在时间窗口内，才增加下载次数
        if current_time - last_download_time > DOWNLOAD_DEDUPE_WINDOW:
            metadata[filename]['download_count'] += 1
            download_time_records[filename] = current_time
    elif action == 'upload':
        metadata[filename]['size'] = file_size
        metadata[filename]['modified'] = file_mtime
    elif action == 'delete' and filename in metadata:  
        del metadata[filename]
        # 同时删除下载时间记录
        if filename in download_time_records:
            del download_time_records[filename]
    
    # 保存元数据
    try:
        with open(METADATA_FILE, 'w', encoding='utf_8') as f:
            json.dump(metadata, f, indent=4, ensure_ascii=False)
    except Exception as e:
        print(f"元数据保存失败:.{e}")
    
    return metadata.get(filename) if action != 'delete' else None


def get_file_list():
    """
    获取上传目录中的文件列表
    
    Returns:
        list: 包含文件信息的字典列表,每个字典包含文件名、大小、修改时间等信息
    
    """
    upload_dir = system_config['upload_folder']
    if not os.path.exists(upload_dir):
        return []
    
    metadata = load_metadata()
    files = []
    
    for filename in os.listdir(upload_dir):  
        # 安全检查，防止目录遍历攻击
        if '../' in filename or not re.match(r'^[\w\-. ]+$', filename):
            continue
        
        file_path = os.path.join(upload_dir, filename)
        if os.path.isfile(file_path):
            try:
                file_info = os.stat(file_path)
                file_meta = metadata.get(filename, {})
                
                files.append({
                    'filename': filename,
                    'name': filename,
                    'size': file_info.st_size,
                    'filesize': file_info.st_size,
                    'modified': file_info.st_mtime,
                    'created': file_info.st_ctime,
                    'download_count': file_meta.get('download_count', 0)
                })
            except Exception as e:
                print(f"获取文件信息失败: {filename}, 错误: {e}")
    
    # 按修改时间排序(最新在上)
    files.sort(key=lambda x: x['modified'], reverse=True)
    
    return files

# ==============================================
# 系统资源与磁盘使用
# ==============================================

def get_disk_usage():
    """
    获取磁盘空间使用情况
    
    Returns:
        dict: 包含系统磁盘和上传目录使用情况的字典
    """
    upload_dir = system_config['upload_folder']
    
    # 确保上传目录存在
    if not os.path.exists(upload_dir):  
        os.makedirs(upload_dir)
    
    # 计算上传目录使用空间
    upload_usage = 0
    for entry in os.scandir(upload_dir):
        if entry.is_file():
            upload_usage += entry.stat().st_size
    
    max_total_bytes = system_config['max_total_size'] * pow(1024, 2)  # MB转Bytes
    
    # 获取系统实际可用空间
    try:
        total, used, free = shutil.disk_usage("/")
        # 实际可用空间取系统可用空间和配置剩余空间的较小值
        available = min(free, max_total_bytes - upload_usage)  
    except:  
        # 回退方案
        available = max_total_bytes - upload_usage
    
    # 计算使用百分比
    usage_percent = 0
    if max_total_bytes > 0:
        usage_percent = min(100, int((upload_usage / max_total_bytes) * 100 ))
    
    return {  
        'system_total': total,
        'system_used': used,
        'system_free': free,
        'upload_total': max_total_bytes,
        'upload_used': upload_usage,
        'available': min(max_total_bytes - upload_usage, free),
        'usage_percent': usage_percent
    }


def get_system_resources():
    """
    获取系统资源信息(CPU、内存、网络接口)
    
    Returns:
        dict: 包含系统资源使用情况的字典
    """
    try:
        # CPU使用率
        cpu_percent = psutil.cpu_percent(interval=1)
        
        # 内存使用率
        mem = psutil.virtual_memory()
        mem_percent = mem.percent
        mem_total = mem.total 
        mem_used = mem.used
        
        #网络接口 
        interfaces = []
        for iface in netifaces.interfaces():
            addrs = netifaces.ifaddresses(iface)
            if netifaces.AF_INET in addrs:
                for link in addrs[netifaces.AF_INET]: 
                    interfaces.append({
                        'interface': iface, 
                        'ip': link['addr']
                    })
        
        return {
            'cpu_percent': cpu_percent,
            'mem_percent': mem_percent,
            'mem_total': mem_total,
            'mem_used': mem_used,
            'interfaces': interfaces
        }
    except Exception as e:
        print(f"获取系统资源失败: {e}")
        # 返回模拟数据
        return { 
            'cpu_percent': '获取系统资源失败',
            'mem_percent': '获取系统资源失',
            'mem_total': '获取系统资源失败',
            'mem_used': '获取系统资源失败',
            'interfaces': [
                {'interface': '本地连接', 'ip': '127.0.0.1'}
            ]
        }

# ===============================================
# 认证与安全
# ===============================================

def require_admin_token(func):
    """
    管理员认证装饰器
    
    检查请求是否包含有效的管理员令牌,用于保护需要管理员权限的接口
    
    Args:
        func:.需要保护的视图函数
    
    Returns:
        wrapper: 装饰后的函数
    """
    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        
        # 优先检查session
        if 'admin_token' in session:
            return func(*args, **kwargs)
            
        # 其次检查请求头
        token = request.headers.get('X-Admin-Token')
        if token and token == session.get('admin_token'):
            
            return func(*args, **kwargs)
            
        return jsonify({"status": "error", "message": "未授权访问"}), 403
    
    return wrapper

# ===============================================
# Git相关功能
# ===============================================

def is_git_installed():
    """
    检查系统是否安装了Git
    
    Returns:
        bool: 如果Git已安装则返回True,否则返回False
    """
    try:
        result = subprocess.run(['git', '--version'], capture_output=True, text=True, timeout=5)
        return result.returncode == 0
    except:
        return False


def install_git():
    """
    安装Git(仅Windows系统)
    
    Returns:
        bool: 如果安装成功则返回True,否则返回False
    """
    if platform.system() != 'Windows':
        return False
    
    try:
        result = subprocess.run(
            ['winget', 'install', '--id', 'Git.Git', '-e', '--source', 'winget'], 
            capture_output=True, text=True, timeout=300
        )
        return result.returncode == 0
    except:
        return False

# ===============================================
# GitHub仓库克隆器
# ===============================================

class GitHubCloner:
    """
    GitHub仓库克隆器
    
    用于异步克隆GitHub仓库并打包为ZIP文件
    """
    
    def __init__(self, repo_url, task_id, branch="main"):
        """
        初始化GitHubCloner实例
        
        Args:
            repo_url (str): GitHub仓库URL
            task_id (str): 任务ID
            branch (str): 要克隆的分支名称,默认为"main"
        """
        self.repo_url = repo_url
        self.task_id = task_id
        self.branch = branch
        self.temp_dir = tempfile.mkdtemp()
        self.zip_path = None
        self.file_name = None
        self.status = "pending"
        self.progress = 0
        self.speed = 0
        self.start_time = time.time()
        self.error = None
        self.clone_dir = None
        self.process = None
        self.cancelled = False
    
    def get_repo_name(self):
        """从仓库URL中提取仓库名称"""
        parsed_url = urlparse(self.repo_url)
        path_parts = parsed_url.path.strip('/').split('/')
        
        if len(path_parts) >= 2:
            return f"{path_parts[0]}_{path_parts[1]}"
        return f"repo_{uuid.uuid4().hex[:8]}"
    
    def cancel(self):
        """取消克隆任务"""
        self.cancelled = True
        self.status = "cancelled"
        if self.process and self.process.poll() is None:
            try:
                # 终止子进程
                self.process.terminate()
                # 等待进程结束
                self.process.wait(timeout=5)
            except Exception as e:
                print(f"取消克隆任务失败: {e}")
    
    def run(self):
        """执行克隆任务的主方法"""
        try:
            self.status = "cloning"
            self.file_name = f"{self.get_repo_name()}_{self.branch}_{int(time.time())}.zip"
            self.clone_dir = os.path.join(self.temp_dir, self.get_repo_name())
            
            # 检查Git是否安装
            if not is_git_installed():
                self.status = "installing_git"
                install_success = install_git()
                if not install_success:
                    self.error = "Git安装失败,请手动安装Git"
                    self.status = "failed"
                    return
            
            # 克隆仓库
            clone_cmd = ['git', 'clone', '--depth', '1', '-b', self.branch, self.repo_url, self.clone_dir]
            self.process = subprocess.Popen(
                clone_cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True
            )
            
            # 监控克隆进度
            self.progress = 10
            start_time = time.time()
            output = []
            
            while self.process.poll() is None and not self.cancelled:
                line = self.process.stdout.readline()
                if line:
                    output.append(line.strip())
                    # 更新进度(模拟)
                    elapsed = time.time() - start_time
                    if elapsed > 30:  # 如果超过30秒仍在克隆,增加进度
                        self.progress = min(80, self.progress + 1)
                
                time.sleep(0.1)
            
            if self.cancelled:
                return
            
            if self.process.returncode != 0:
                self.error = "\n".join(output[-5:])  # 保存最后5行输出作为错误信息
                self.status = "failed"
                return
            
            # 创建ZIP文件
            self.status = "compressing"
            self.progress = 85
            
            # 创建ZIP压缩文件
            zipf = zipfile.ZipFile(self.zip_path, 'w', zipfile.ZIP_DEFLATED)
            
            # 遍历目录并添加到ZIP
            for root, dirs, files in os.walk(self.clone_dir):
                for file in files:
                    file_path = os.path.join(root, file)
                    arcname = os.path.relpath(file_path, self.temp_dir)
                    zipf.write(file_path, arcname)
            
            zipf.close()
            
            self.progress = 100
            self.status = "completed"
            
        except Exception as e:
            self.error = str(e)
            self.status = "failed"
        finally:
            # 清理临时文件
            if os.path.exists(self.temp_dir):
                try:
                    shutil.rmtree(self.temp_dir)
                except Exception as e:
                    print(f"清理临时文件失败: {e}")

# ===============================================
# 多文件上传与GitHub克隆线程
# ===============================================

# GitHub仓库克隆线程
class GitHubCloneThread(threading.Thread):
    def __init__(self):
        super().__init__(daemon=True)
        self.running = True

    def run(self):
        while self.running:
            try:
                cloner = github_clone_queue.get(timeout=1)
                # 添加到活动克隆器
                with github_clone_lock:
                    active_cloners[cloner.task_id] = cloner
                
                cloner.run()
                
                # 更新任务状态
                with github_clone_lock:
                    github_clone_tasks[cloner.task_id] = {
                        "status": cloner.status,
                        "progress": cloner.progress,
                        "repo_url": cloner.repo_url,
                        "file_name": cloner.file_name,
                        "error": cloner.error,
                        "start_time": cloner.start_time,
                        "branch": cloner.branch
                    }
                
                # 从活动克隆器中移除
                if cloner.task_id in active_cloners:
                    del active_cloners[cloner.task_id]
                
                github_clone_queue.task_done()
            except queue.Empty:
                pass

    def stop(self):
        self.running = False

# 启动GitHub克隆线程
github_clone_thread = GitHubCloneThread()
github_clone_thread.start()

# 确保上传目录存在
if not os.path.exists(system_config['upload_folder']):
    os.makedirs(system_config['upload_folder'])

# 多文件上传队列
upload_queue = queue.Queue()
upload_tasks = {}

# 多文件上传线程
class UploadThread(threading.Thread):
    def __init__(self):
        super().__init__(daemon=True)
        self.running = True

    def run(self):
        while self.running:
            try:
                task = upload_queue.get(timeout=1)
                task.upload()
                upload_queue.task_done()
            except queue.Empty:
                pass

    def stop(self):
        self.running = False

# 启动上传线程
upload_thread = UploadThread()
upload_thread.start()

# 上传任务类
class UploadTask:
    def __init__(self, file, task_id):
        self.file = file
        self.task_id = task_id
        self.filename = secure_filename(file.filename)
        self.status = 'queued'
        self.progress = 0
        self.start_time = time.time()
        self.error = None

    def upload(self):
        try:
            self.status = 'uploading'
            # 更新任务状态
            with upload_lock:
                upload_tasks[self.task_id] = {
                    'status': self.status,
                    'progress': self.progress,
                    'filename': self.filename
                }
            
            # 创建文件路径
            file_path = os.path.join(system_config['upload_folder'], self.filename)
            
            # 处理重名文件
            counter = 1
            name, ext = os.path.splitext(self.filename)
            while os.path.exists(file_path):
                new_name = f"{name}_{counter}{ext}"
                file_path = os.path.join(system_config['upload_folder'], new_name)
                counter += 1
            self.filename = new_name
            
            # 保存文件
            self.file.save(file_path)
            
            # 更新状态
            self.status = 'completed'
            self.progress = 100
        except Exception as e:
            self.status = 'failed'
            self.error = str(e)
        finally:
            # 更新任务状态
            with upload_lock:
                upload_tasks[self.task_id] = {
                    'status': self.status,
                    'progress': self.progress,
                    'filename': self.filename,
                    'error': self.error
                }

# ===============================================
# 离线下载工作线程
# ===============================================

# 全局变量：活动下载器映射表
active_downloaders = {}
# 全局变量：离线下载锁
offline_download_lock = threading.Lock()

def download_chunk(url, start, end, task_id, chunk_index, temp_dir):
    """
    下载文件的一个片段
    """
    headers = {'Range': f'bytes={start}-{end}'}
    try:
        response = requests.get(url, headers=headers, stream=True, timeout=30)
        chunk_path = os.path.join(temp_dir, f"chunk_{chunk_index}")
        with open(chunk_path, 'wb') as f:
            for chunk in response.iter_content(chunk_size=8192):
                # 检查任务是否被取消
                with offline_download_lock:
                    if task_id in active_downloaders and active_downloaders[task_id].cancelled:
                        return chunk_index, "任务已取消"
                f.write(chunk)
        return chunk_index, None
    except Exception as e:
        return chunk_index, str(e)

class OfflineDownloader:
    """
    离线下载器类
    """
    def __init__(self, task_id, url):
        self.task_id = task_id
        self.url = url
        self.cancelled = False
        self.temp_dir = None
    
    def cancel(self):
        """
        取消下载任务
        """
        self.cancelled = True
    
    def run(self):
        """
        执行下载任务
        """
        task = OFFLINE_TASKS.get(self.task_id)
        if not task:
            return
        
        try:
            # 更新任务状态
            task['status'] = 'downloading'
            task['started'] = datetime.now().isoformat()
            url = self.url
            
            # 获取文件大小
            head_resp = requests.head(url, timeout=10)
            total_size = int(head_resp.headers.get('content-length', 0))
            task['total_size'] = total_size
            
            # 生成文件名
            content_disposition = head_resp.headers.get('content-disposition', '')
            if 'filename=' in content_disposition:
                filename = content_disposition.split('filename=')[1].strip('"\'')
            else:
                filename = os.path.basename(urlparse(url).path) or f"download_{int(time.time())}"
            task['filename'] = filename
            
            # 检查是否已取消
            if self.cancelled:
                task['status'] = 'cancelled'
                return
            
            # 创建临时目录
            self.temp_dir = tempfile.mkdtemp()
            
            # 如果文件大小未知或较小，使用单线程下载
            if total_size == 0:
                # 使用单线程下载
                save_path = os.path.join(system_config['upload_folder'], filename)
                response = requests.get(url, stream=True, timeout=60)
                with open(save_path, 'wb') as f:
                    downloaded = 0
                    for chunk in response.iter_content(chunk_size=8192):
                        # 检查任务是否被取消
                        if self.cancelled:
                            task['status'] = 'cancelled'
                            return
                        
                        if chunk:
                            f.write(chunk)
                            downloaded += len(chunk)
                            task['progress'] = int((downloaded / total_size) * 100) if total_size > 0 else 0
            else:
                # 多线程下载：分为8个线程（可根据需要调整）
                num_threads = min(8, max(1, total_size // (5 * 1024 * 1024)))  # 每5MB一个线程
                chunk_size = total_size // num_threads
                ranges = []
                for i in range(num_threads):
                    start = i * chunk_size
                    end = start + chunk_size - 1 if i < num_threads - 1 else total_size - 1
                    ranges.append((start, end))
                
                # 使用线程池下载片段
                futures = []
                with concurrent.futures.ThreadPoolExecutor(max_workers=num_threads) as executor:
                    for i, (start, end) in enumerate(ranges):
                        # 检查任务是否已被取消
                        if self.cancelled:
                            task['status'] = 'cancelled'
                            return
                        future = executor.submit(download_chunk, url, start, end, self.task_id, i, self.temp_dir)
                        futures.append(future)
                
                # 等待所有片段下载完成
                errors = []
                for future in concurrent.futures.as_completed(futures):
                    # 检查任务是否已被取消
                    if self.cancelled:
                        task['status'] = 'cancelled'
                        return
                    
                    chunk_index, error = future.result()
                    if error:
                        errors.append(f"片段{chunk_index}下载失败: {error}")
                
                if errors:
                    raise Exception(", ".join(errors))
                
                # 检查任务是否已被取消
                if self.cancelled:
                    task['status'] = 'cancelled'
                    return
                
                # 合并片段
                save_path = os.path.join(system_config['upload_folder'], filename)
                with open(save_path, 'wb') as outfile:
                    for i in range(num_threads):
                        chunk_path = os.path.join(self.temp_dir, f"chunk_{i}")
                        with open(chunk_path, 'rb') as infile:
                            shutil.copyfileobj(infile, outfile)
                
                # 检查任务是否已被取消
                if self.cancelled:
                    task['status'] = 'cancelled'
                    # 删除已下载的文件
                    if os.path.exists(save_path):
                        try:
                            os.remove(save_path)
                        except Exception:
                            pass
                    return
            
            # 更新元数据
            file_size = os.path.getsize(save_path)
            update_metadata(filename, 'upload', file_size)
            
            # 任务完成
            task['status'] = 'completed'
            task['progress'] = 100
            task['completed'] = datetime.now().isoformat()
            
        except Exception as e:
            if not self.cancelled:
                task['status'] = 'failed'
                task['error'] = str(e)
            else:
                task['status'] = 'cancelled'
        finally:
            # 清理临时目录
            if self.temp_dir and os.path.exists(self.temp_dir):
                try:
                    shutil.rmtree(self.temp_dir)
                except Exception:
                    pass
            # 从活动下载器中移除
            with offline_download_lock:
                if self.task_id in active_downloaders:
                    del active_downloaders[self.task_id]

def offline_download_worker():
    """
    离线下载工作线程
    """
    while True:
        try:
            task_id = OFFLINE_QUEUE.get(timeout=10)
            task = OFFLINE_TASKS.get(task_id)
            
            if not task:
                OFFLINE_QUEUE.task_done()
                continue
            
            # 检查任务是否已被取消
            if task['status'] == 'cancelled':
                OFFLINE_QUEUE.task_done()
                continue
                
            try:
                # 创建下载器并添加到活动下载器映射表
                downloader = OfflineDownloader(task_id, task['url'])
                with offline_download_lock:
                    active_downloaders[task_id] = downloader
                
                # 执行下载
                downloader.run()
                
            finally:
                OFFLINE_QUEUE.task_done()
                
        except queue.Empty:
            continue

# 启动工作线程
threading.Thread(target=offline_download_worker, daemon=True).start()


# ===============================================
# 实用工具函数
# ===============================================

def convert_size(size_bytes):
    """
    根据文件大小自动选择合适的单位
    
    Args:
        size_bytes (int/str): 字节数(支持整数或字符串类型的数值)
    
    Returns:
        str: 带单位的格式化大小字符串
    """
    # 添加类型转换和错误处理
    try:
        size_bytes = int(size_bytes)
    except (ValueError, TypeError):
        return "0B"  # 转换失败时返回默认值
    
    if size_bytes == 0:
        return "0B"
    units = ("B", "KB", "MB", "GB", "TB")
    i = 0
    size = size_bytes
    
    while size >= 1024 and i < len(units)-1:
        size /= 1024.0
        i += 1
    
    # 根据大小选择合适的精度
    if size < 10:
        return f"{size:.2f} {units[i]}"
    elif size < 100:
        return f"{size:.1f} {units[i]}"
    else:
        return f"{size:.0f} {units[i]}"

# ===============================================
# Flask路由定义
# ===============================================

# 管理员相关路由
@app.route('/admin')
def admin():
    """管理员控制面板页面"""
    # 检查管理员登录状态
    if 'admin_token' not in session:
        # 重定向到客户端登录页面
        return redirect('/admin/login')
    
    disk_info = get_disk_usage()  # 获取磁盘信息
    sys_resources = get_system_resources()  # 获取系统资源信息
    
    # 构建disk_space字典以匹配模板需求
    disk_space = {
        'percent': disk_info['usage_percent'],
        'used': disk_info['upload_used'],
        'free': disk_info['available'],
        'total': disk_info['upload_total']
    }
    
    # 获取其他需要的数据
    files = get_file_list()
    share_folder = system_config['upload_folder']
    disk = get_disk_usage()
    
    return render_template(
        'admin.html',
        disk_space=disk_space,
        files=files,
        system_config=system_config,
        share_folder=share_folder,
        max_file_size=system_config['max_file_size'],
        max_total_size=system_config['max_total_size'],
        system_total=convert_size(disk['system_total']),
        system_used=convert_size(disk['system_used']),
        upload_used=convert_size(disk['upload_used']),
        upload_total=convert_size(disk['upload_total']),
        service_start=SERVICE_START_TIME.strftime("%Y-%m-%d %H:%M:%S"),
        uptime=str(datetime.now() - SERVICE_START_TIME),
        # 系统资源信息
        cpu_percent=sys_resources['cpu_percent'],
        mem_percent=sys_resources['mem_percent'],
        mem_total=convert_size(sys_resources['mem_total']),
        mem_used=convert_size(sys_resources['mem_used']),
        interfaces=sys_resources['interfaces'],
        # 网络配置
        port=system_config['port'],
        network_interface=system_config['network_interface'],
        # 极验验证配置
        geetest_id=system_config['geetest_id'],
        geetest_key=system_config['geetest_key']
        
    )


@app.route('/admin/login', methods=['GET'], endpoint='admin_login_get')
def admin_login_get():
    """管理员登录页面"""
    return render_template('admin_login.html')


@app.route('/admin/login', methods=['POST'], endpoint='admin_login_post')
def admin_login_post():
    """管理员登录API"""
    data = request.get_json()
    username = data.get('username')
    password = data.get('password')
    
    print(f"收到管理员登录请求: 用户名={username}")
    
    
    if username == system_config['admin_user'] and password == system_config['admin_password']:
        session_token = os.urandom(24).hex()
        session['admin_token'] = session_token
        return jsonify({"status": "success", "token": session_token})
    
    return jsonify({"status": "error", "message": "无效凭据"}), 401


@app.route('/admin/change_password', methods=['POST'], endpoint='admin_change_password')
def admin_change_password():
    # 获取表单数据
    current_password = request.form.get('current_password')
    new_password = request.form.get('new_password')
    confirm_password = request.form.get('confirm_password')
    
    # 验证当前密码
    if current_password != system_config['admin_password']:
        flash('当前密码不正确', 'error')
        return redirect(url_for('admin'))
    
    # 验证新密码匹配
    if new_password != confirm_password:
        flash('新密码不匹配', 'error')
        return redirect(url_for('admin'))
    
    # 更新密码
    system_config['admin_password'] = new_password
    save_config()
    
    flash('密码已成功更新', 'success')
    return redirect(url_for('admin'))


@app.route('/admin/logout')
def admin_logout():
    """管理员登出"""
    session.pop('admin_token', None)
    return redirect('/admin/login')


@app.route('/admin/github_clone')
def admin_github_clone():
    """GitHub仓库克隆管理页面"""
    # 检查管理员登录状态
    if 'admin_token' not in session:
        return redirect('/admin/login')
    
    # 获取磁盘使用情况
    disk = get_disk_usage()
    # 获取文件列表
    files = get_file_list()
    
    return render_template(
        'github_clone.html',
        files=files,
        disk=disk,
        max_file_size=system_config['max_file_size'],
        max_total_size=system_config['max_total_size'],
        upload_folder=system_config['upload_folder']
    )


# 文件操作API
@app.route('/api/files')
def api_files():
    """获取文件列表API"""
    files = get_file_list()
    disk = get_disk_usage()
    
    # 添加前端需要的字段
    formatted_files = []
    for file in files:
        formatted_files.append({
            'filename': file['filename'],
            'name': file['name'],
            'size': file['size'],
            'modified': file['modified'],
            'download_count': file['download_count'],
            # 添加 hash 字段(这里用文件名代替)
            'hash': file['name']
        })
    
    return jsonify({
        'files': formatted_files,
        'disk_used': disk['upload_used'],
        'max_storage': system_config['max_total_size'] * 1024 * 1024
    })


@app.route('/api/upload', methods=['POST'])
def upload():
    """文件上传API"""
    if 'file' not in request.files:
        return jsonify({"status": "error", "message": "未选择文件"})
    
    file = request.files['file']
    
    # 验证文件名
    if not file.filename or '.' not in file.filename:
        return jsonify({"status": "error", "message": "无效的文件名"})
    
    # 获取文件大小(更可靠的方法)
    file.seek(0, os.SEEK_END)
    file_size = file.tell()
    file.seek(0)  # 重置文件指针
    
    # 检查单个文件大小限制
    max_size = system_config['max_file_size'] * 1024 * 1024
    if file_size > max_size:
        return jsonify({
            "status": "error",
            "message": f"文件大小超过限制 ({convert_size(max_size)})"
        })
    
    # 检查总空间(更严格的检查)
    disk = get_disk_usage()
    if file_size > disk['available']:
        return jsonify({
            "status": "error",
            "message": f"磁盘空间不足(可用空间：{convert_size(disk['available'])})"
        })
    
    # 添加全局上传锁,防止并发上传导致空间超限
    with upload_lock:
        # 再次检查空间(防止在检查期间有其他文件上传)
        disk = get_disk_usage()
        if file_size > disk['available']:
            return jsonify({
                "status": "error",
                "message": "空间不足,请稍后再试"
            })
        
        # 安全保存文件
        filename = secure_filename(file.filename)
        save_path = os.path.join(system_config['upload_folder'], filename)
        
        # 处理重名文件
        counter = 1
        name, ext = os.path.splitext(filename)
        new_name = filename  # 初始化new_name变量
        while os.path.exists(save_path):
            new_name = f"{name}_{counter}{ext}"
            save_path = os.path.join(system_config['upload_folder'], new_name)
            counter += 1
        filename = new_name
        
        try:
            file.save(save_path)
            update_metadata(filename, 'upload')
            return jsonify({"status": "success", "filename": filename})
        except Exception as e:
            return jsonify({"status": "error", "message": f"保存失败: {str(e)}"})


@app.route('/api/delete_file', methods=['POST'])
@require_admin_token
def api_delete_file():
    """删除文件API"""
    try:
        # 从JSON数据获取文件名
        data = request.get_json()
        filename = data.get('filename')
        
        if not filename:
            return jsonify({"status": "error", "message": "文件名不能为空"}), 400
        
        # 安全检查，防止目录遍历攻击
        if '../' in filename or not re.match(r'^[\w\-. ]+$', filename):
            return jsonify({"status": "error", "message": "无效的文件名"}), 400
        
        file_path = os.path.join(system_config['upload_folder'], filename)
        
        # 确保文件在上传目录内
        real_upload_dir = os.path.realpath(system_config['upload_folder'])
        real_file_path = os.path.realpath(file_path)
        
        if not real_file_path.startswith(real_upload_dir):
            return jsonify({"status": "error", "message": "文件不在上传目录内"}), 400
        
        if not os.path.exists(file_path):
            return jsonify({"status": "error", "message": "文件不存在"}), 404
        
        try:
            os.remove(file_path)
            # 更新元数据
            update_metadata(filename, 'delete')
            return jsonify({"status": "success", "message": "文件已删除"})
        except Exception as e:
            return jsonify({"status": "error", "message": f"删除失败: {str(e)}"}), 500
    except Exception as e:
        return jsonify({"status": "error", "message": f"请求处理失败: {str(e)}"}), 500


#多文件上传路由
@app.route('/multi_upload', methods=['GET'])
def upload_multi_page():
    """多文件上传页面"""
    return render_template('multi_upload.html',
                           app_name=system_config['app_name'],
                           max_file_size=system_config['max_file_size'],
                           max_total_size=system_config['max_total_size'],
                           upload_folder=system_config['upload_folder']
                           )

# 多文件上传API
@app.route('/api/multi_upload', methods=['POST'])
def upload_multi():
    """多文件上传API"""
    if 'file' not in request.files:
        return jsonify({"status": "error", "message": "未选择文件"}), 400
    
    file = request.files['file']
    
    # 验证文件名
    if not file.filename or '.' not in file.filename:
        return jsonify({"status": "error", "message": "无效的文件名"}), 400
    
    # 获取文件大小
    file.seek(0, os.SEEK_END)
    file_size = file.tell()
    file.seek(0)  # 重置文件指针
    
    # 检查单个文件大小限制
    max_size = system_config['max_file_size'] * 1024 * 1024
    if file_size > max_size:
        return jsonify({
            "status": "error",
            "message": f"文件大小超过限制 ({convert_size(max_size)})"
        }), 400
    
    # 检查总空间
    disk = get_disk_usage()
    if file_size > disk['available']:
        return jsonify({
            "status": "error",
            "message": f"磁盘空间不足（可用空间：{convert_size(disk['available'])}）"
        }), 400
    
    # 添加全局上传锁
    with upload_lock:
        # 再次检查空间
        disk = get_disk_usage()
        if file_size > disk['available']:
            return jsonify({
                "status": "error",
                "message": "空间不足，请稍后再试"
            }), 400
        
        # 安全保存文件
        filename = secure_filename(file.filename)
        save_path = os.path.join(system_config['upload_folder'], filename)
        
        # 处理重名文件
        counter = 1
        name, ext = os.path.splitext(filename)
        while os.path.exists(save_path):
            new_name = f"{name}_{counter}{ext}"
            save_path = os.path.join(system_config['upload_folder'], new_name)
            counter += 1
            filename = new_name
        
        try:
            file.save(save_path)
            update_metadata(filename, 'upload')
            return jsonify({"status": "success", "filename": filename})
        except Exception as e:
            return jsonify({"status": "error", "message": f"保存失败: {str(e)}"}), 500


# GitHub克隆相关API
@app.route('/api/github_clone', methods=['POST'])
def add_github_clone():
    """添加GitHub克隆任务API"""
    if 'admin_token' not in session:
        return jsonify({"status": "error", "message": "未授权访问"}), 403
    
    # 检查Git是否安装
    if not is_git_installed():
        # 尝试安装Git(仅Windows)
        if platform.system() == 'Windows':
            if not install_git():
                return jsonify({
                    "status": "error",
                    "message": "Git未安装且自动安装失败",
                    "install_link": "https://git-scm.com/downloads"
                }), 400
        else:
            return jsonify({
                "status": "error",
                "message": "Git未安装",
                "install_link": "https://git-scm.com/downloads"
            }), 400
    
    data = request.get_json()
    repo_url = data.get('repo_url')
    branch = data.get('branch', 'main')
    
    if not repo_url:
        return jsonify({"status": "error", "message": "未提供仓库URL"}), 400
    
    # 创建克隆任务
    task_id = hashlib.md5(f"{repo_url}{time.time()}".encode()).hexdigest()[:8]
    cloner = GitHubCloner(repo_url, task_id, branch)
    
    # 添加到队列
    github_clone_queue.put(cloner)
    
    # 初始化任务状态
    with github_clone_lock:
        github_clone_tasks[task_id] = {
            "status": "pending",
            "progress": 0,
            "repo_url": repo_url,
            "file_name": None,
            "error": None,
            "start_time": time.time(),
            "branch": branch
        }
    
    return jsonify({"status": "success", "task_id": task_id})


@app.route('/api/github_clone/tasks', methods=['GET'])
def get_github_clone_tasks():
    """获取GitHub克隆任务列表API"""
    if 'admin_token' not in session:
        return jsonify({"status": "error", "message": "未授权访问"}), 403
    
    with github_clone_lock:
        return jsonify({
            "tasks": github_clone_tasks.values(),
            "active_count": github_clone_queue.qsize(),
            "thread_active": github_clone_thread.is_alive()
        })


@app.route('/api/github_clone/cancel_task', methods=['POST'])
def cancel_github_clone_task():
    """取消GitHub克隆任务API"""
    if 'admin_token' not in session:
        return jsonify({"status": "error", "message": "未授权访问"}), 403
    
    data = request.get_json()
    task_id = data.get('task_id')
    
    if not task_id:
        return jsonify({"status": "error", "message": "未提供任务ID"}), 400
    
    with github_clone_lock:
        # 检查任务是否在活动克隆器中
        if task_id in active_cloners:
            try:
                active_cloners[task_id].cancel()
                # 更新任务状态
                if task_id in github_clone_tasks:
                    github_clone_tasks[task_id]['status'] = 'cancelled'
                return jsonify({"status": "success", "message": "任务已取消"})
            except Exception as e:
                return jsonify({"status": "error", "message": f"取消任务失败: {str(e)}"}), 500
        elif task_id in github_clone_tasks:
            # 如果任务不在活动状态,但存在于任务列表中
            github_clone_tasks[task_id]['status'] = 'cancelled'
            return jsonify({"status": "success", "message": "任务已标记为取消"})
        else:
            return jsonify({"status": "error", "message": "任务不存在"}), 404


# 系统信息API
@app.route('/api/sysinfo')
def api_sysinfo():
    """获取系统信息API"""
    disk = get_disk_usage()
    files = get_file_list()
    total_downloads = sum(f['download_count'] for f in files)
    
    return jsonify({
        'disk': disk,
        'config': {
            'max_file_size': system_config['max_file_size'],
            'max_total_size': system_config['max_total_size'],
            'app_name': system_config['app_name'],
            'app_version': system_config['app_version']
        },
        'file_count': len(files),
        'service_start': SERVICE_START_TIME.isoformat(),
        'uptime': str(datetime.now() - SERVICE_START_TIME),
        'total_downloads': total_downloads
    })


@app.route('/api/system/config')
def get_system_config():
    """获取系统配置API"""
    return jsonify({
        'max_file_size': system_config['max_file_size'],
        'max_total_size': system_config['max_total_size'],
        'app_name': system_config['app_name'],
        'app_version': system_config['app_version']
    })


@app.route('/api/update_config', methods=['POST'], endpoint='update_config')
@require_admin_token
def api_update_config():
    """更新系统配置API"""
    try:
        data = request.get_json()
        
        # 更新存储配置
        if 'max_storage' in data:
            max_storage = float(data['max_storage'])
            if max_storage <= 0:
                return jsonify({"status": "error", "message": "存储空间必须大于0"}), 400
            system_config['max_total_size'] = max_storage * 1024  # GB转MB
        
        if 'max_file_size' in data:
            max_file_size = float(data['max_file_size'])
            if max_file_size <= 0:
                return jsonify({"status": "error", "message": "文件大小必须大于0"}), 400
            system_config['max_file_size'] = max_file_size
        
        # 更新极验配置
        if 'geetest_id' in data:
            system_config['geetest_id'] = data['geetest_id']

        if 'geetest_key' in data:
            system_config['geetest_key'] = data['geetest_key']
            
        # 更新离线下载配置
        if 'offline_download_enabled' in data:
            system_config['offline_download_enabled'] = data['offline_download_enabled'] == 'on' or data['offline_download_enabled'] == True
        else:
            # 如果没有发送此参数，默认为禁用
            system_config['offline_download_enabled'] = False

        # 更新端口配置
        if 'port' in data:
            port = int(data['port'])
            if port < 1024 or port > 65535:
                return jsonify({"status": "error", "message": "端口必须在1024-65535之间"}), 400
            system_config['port'] = port
        
        # 更新网络接口配置
        if 'network_interface' in data:
            system_config['network_interface'] = data['network_interface']
        
        save_config()
        return jsonify({"status": "success", "config": system_config})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 400


# 页面路由
@app.route('/index')
def index():
    """文件下载中心首页"""
    disk = get_disk_usage()
    files = get_file_list()
    
    return render_template(
        'index.html',
        files=files,
        app_name=system_config['app_name'],
        total_space=convert_size(disk['upload_total']),
        used_space=convert_size(disk['upload_used']),
        free_space=convert_size(disk['available']),
        max_file_size=system_config['max_file_size'],
        usage_percent=disk['usage_percent']
    )


@app.route('/download/<filename>')
def download(filename):
    """文件下载路由"""
    if '../' in filename or not re.match(r'^[\w\-. ]+$', filename):
        abort(400)
    
    upload_dir = system_config['upload_folder']
    file_path = os.path.join(upload_dir, filename)
    
    if not os.path.isfile(file_path):
        abort(404)
    
    update_metadata(filename, 'download')
    return send_from_directory(upload_dir, filename, as_attachment=True)


@app.route('/preview/<filename>')
def preview(filename):
    """文件预览路由"""
    if '../' in filename or not re.match(r'^[\w\-. ]+$', filename):
        abort(400)
    
    upload_dir = system_config['upload_folder']
    file_path = os.path.join(upload_dir, filename)
    
    if not os.path.isfile(file_path):
        abort(404)
    
    return send_from_directory(upload_dir, filename)


@app.route('/captcha_settings')
@require_admin_token
def captcha_settings():
    """验证码设置页面"""
    return render_template('captcha_settings.html', system_config=system_config)


@app.route('/')
def download_page():
    """文件下载中心页面"""
    return render_template('download_page.html')


# 离线下载路由
@app.route('/offline_download')
def offline_download_page():
    """离线下载页面"""
    return render_template('offline_download.html',
                           geetest_id=system_config.get('geetest_id'),
                           app_name=system_config['app_name'])

# 离线下载任务处理类
class OfflineDownloader:
    """离线下载任务处理类"""
    def __init__(self, task_id, url, filename):
        self.task_id = task_id
        self.url = url
        self.filename = filename
        self.status = "downloading"
        self.progress = 0
        self.speed = 0
        self.error = None
        self.temp_file = None
        self.cancelled = False
        self.start_time = time.time()
        
    def cancel(self):
        """取消下载任务"""
        self.cancelled = True
        self.status = "cancelled"
        
    def run(self):
        """执行下载任务"""
        try:
            # 更新任务状态
            OFFLINE_TASKS[self.task_id]['status'] = 'downloading'
            
            # 创建临时文件
            temp_dir = tempfile.mkdtemp()
            self.temp_file = os.path.join(temp_dir, self.filename)
            
            # 开始下载
            with requests.get(self.url, stream=True, allow_redirects=True) as r:
                r.raise_for_status()
                
                # 获取文件总大小
                total_size = int(r.headers.get('content-length', 0))
                downloaded_size = 0
                
                # 保存文件
                with open(self.temp_file, 'wb') as f:
                    for chunk in r.iter_content(chunk_size=8192):
                        if self.cancelled:
                            break
                        
                        if chunk:
                            f.write(chunk)
                            downloaded_size += len(chunk)
                            
                            # 更新进度
                            if total_size > 0:
                                self.progress = int((downloaded_size / total_size) * 100)
                            else:
                                # 未知文件大小，按时间估计进度
                                elapsed = time.time() - self.start_time
                                self.progress = min(95, int(elapsed / 60 * 100))
                            
                            OFFLINE_TASKS[self.task_id]['progress'] = self.progress
                            
            if self.cancelled:
                return
            
            # 检查文件是否下载完成
            if os.path.exists(self.temp_file) and os.path.getsize(self.temp_file) > 0:
                # 移动到上传目录
                upload_path = os.path.join(system_config['upload_folder'], self.filename)
                
                # 处理重名文件
                counter = 1
                name, ext = os.path.splitext(self.filename)
                while os.path.exists(upload_path):
                    new_name = f"{name}_{counter}{ext}"
                    upload_path = os.path.join(system_config['upload_folder'], new_name)
                    counter += 1
                
                shutil.move(self.temp_file, upload_path)
                
                # 更新元数据
                update_metadata(os.path.basename(upload_path), 'upload')
                
                # 更新任务状态
                OFFLINE_TASKS[self.task_id]['status'] = 'completed'
                OFFLINE_TASKS[self.task_id]['progress'] = 100
                OFFLINE_TASKS[self.task_id]['filename'] = os.path.basename(upload_path)
            else:
                raise Exception("文件下载失败，文件为空或不存在")
                
        except Exception as e:
            self.error = str(e)
            OFFLINE_TASKS[self.task_id]['status'] = 'failed'
            OFFLINE_TASKS[self.task_id]['error'] = self.error
        finally:
            # 清理临时文件
            if self.temp_file and os.path.exists(os.path.dirname(self.temp_file)):
                try:
                    shutil.rmtree(os.path.dirname(self.temp_file))
                except Exception as e:
                    print(f"清理临时文件失败: {e}")

# 离线下载线程
class OfflineDownloadThread(threading.Thread):
    """离线下载线程"""
    def __init__(self):
        super().__init__(daemon=True)
        self.running = True
        
    def run(self):
        while self.running:
            try:
                task_id = OFFLINE_QUEUE.get(timeout=1)
                task = OFFLINE_TASKS.get(task_id)
                
                if task:
                    downloader = OfflineDownloader(
                        task_id,
                        task['url'],
                        task['filename']
                    )
                    
                    # 添加到活动下载器
                    with offline_download_lock:
                        active_downloaders[task_id] = downloader
                    
                    downloader.run()
                    
                    # 从活动下载器中移除
                    with offline_download_lock:
                        if task_id in active_downloaders:
                            del active_downloaders[task_id]
                    
                OFFLINE_QUEUE.task_done()
            except queue.Empty:
                pass
            
    def stop(self):
        self.running = True

# 初始化离线下载相关变量
OFFLINE_QUEUE = queue.Queue()
OFFLINE_TASKS = {}
active_downloaders = {}
offline_download_lock = threading.Lock()

# 启动离线下载线程
offline_download_thread = OfflineDownloadThread()
offline_download_thread.start()

@app.route('/api/offline_download', methods=['POST'])
def api_offline_download():
    """添加离线下载任务API"""
    # 检查离线下载功能是否启用
    if not system_config.get('offline_download_enabled', False):
        return jsonify({"status": "error", "message": "离线下载功能未启用"}), 403
    
    data = request.get_json()
    url = data.get('url')
    geetest = data.get('geetest', {})
    
    # 验证URL
    if not url or not re.match(r'^https?://', url):
        return jsonify({"status": "error", "message": "无效的URL"}), 400
    
    # 验证极验验证码
    captcha_id = system_config.get('geetest_id', '')
    captcha_key = system_config.get('geetest_key', '')
    
    if not captcha_id or not captcha_key:
        return jsonify({"status": "error", "message": "验证码未配置"}), 500
    
    # 验证极验参数
    if not geetest.get('lot_number') or not geetest.get('captcha_output') or not geetest.get('pass_token') or not geetest.get('gen_time'):
        return jsonify({"status": "error", "message": "验证参数缺失"}), 400
    
    # 验证极验
    try:
        # 生成签名
        sign_token = hmac.new(
            captcha_key.encode(),
            geetest['lot_number'].encode(),
            digestmod=hashlib.sha256
        ).hexdigest()
        
        # 验证请求
        response = requests.post(
            "https://gcaptcha4.geetest.com/validate",
            params={"captcha_id": captcha_id},
            data={
                "lot_number": geetest['lot_number'],
                "captcha_output": geetest['captcha_output'],
                "pass_token": geetest['pass_token'],
                "gen_time": geetest['gen_time'],
                "sign_token": sign_token
            }
        )
        
        if response.status_code != 200:
            return jsonify({"status": "error", "message": "验证服务异常"}), 500
            
        result = response.json()
        if result.get('result') != 'success':
            return jsonify({"status": "error", "message": "验证失败"}), 403
    except Exception as e:
        return jsonify({"status": "error", "message": f"验证错误: {str(e)}"}), 500
    
    # 创建离线下载任务
    task_id = str(uuid.uuid4())
    filename = os.path.basename(urlparse(url).path) or f"download_{int(time.time())}"
    
    # 确保文件名有效
    filename = secure_filename(filename)
    if not filename:
        filename = f"download_{int(time.time())}"
    
    OFFLINE_TASKS[task_id] = {
        "id": task_id,
        "url": url,
        "filename": filename,
        "status": "queued",
        "progress": 0,
        "created": datetime.now().isoformat()
    }
    
    # 添加到下载队列
    OFFLINE_QUEUE.put(task_id)
    
    return jsonify({
        "status": "success",
        "task_id": task_id,
        "message": "下载任务已添加"
    })


# 清理下载列表API
@app.route('/api/offline_tasks/clear', methods=['POST'])
def clear_offline_tasks():
    """清空已完成/失败的离线任务"""
    to_delete = []
    for task_id, task in OFFLINE_TASKS.items():
        if task['status'] in ['completed', 'failed', 'cancelled']:
            to_delete.append(task_id)
    
    for task_id in to_delete:
        del OFFLINE_TASKS[task_id]
    
    return jsonify({"status": "success", "count": len(to_delete)})

# 取消离线下载任务API
@app.route('/api/offline_tasks/cancel', methods=['POST'])
def cancel_offline_task():
    """取消离线下载任务"""
    data = request.get_json()
    task_id = data.get('task_id')
    
    if not task_id:
        return jsonify({"status": "error", "message": "任务ID不能为空"}), 400
    
    # 检查任务是否存在
    if task_id not in OFFLINE_TASKS:
        return jsonify({"status": "error", "message": "任务不存在"}), 404
    
    # 检查任务状态
    task = OFFLINE_TASKS[task_id]
    if task['status'] in ['completed', 'failed', 'cancelled']:
        return jsonify({"status": "error", "message": f"任务已{task['status']}，无法取消"}), 400
    
    # 尝试取消任务
    try:
        with offline_download_lock:
            if task_id in active_downloaders:
                active_downloaders[task_id].cancel()
                OFFLINE_TASKS[task_id]['status'] = 'cancelled'
                return jsonify({"status": "success", "message": "任务已取消"})
            else:
                # 任务在队列中，直接标记为取消
                OFFLINE_TASKS[task_id]['status'] = 'cancelled'
                return jsonify({"status": "success", "message": "任务已标记为取消"})
    except Exception as e:
        return jsonify({"status": "error", "message": f"取消任务失败: {str(e)}"}), 500


# 获取离线下载任务列表API
@app.route('/api/offline_tasks', methods=['GET'])
def get_offline_tasks():
    """获取离线下载任务列表"""
    # 确保返回的任务信息是安全的
    safe_tasks = []
    for task in OFFLINE_TASKS.values():
        safe_task = {
            'id': task['id'],
            'url': task['url'],
            'filename': task['filename'],
            'status': task['status'],
            'progress': task['progress'],
            'created': task['created'],
            'error': task.get('error', None)
        }
        safe_tasks.append(safe_task)
    
    return jsonify({
        "status": "success",
        "tasks": safe_tasks
    })


#文件详情页面路由
@app.route('/file_detail')
def file_detail():
    """文件详情页"""
    filename = request.args.get('file')
    if not filename:
        return redirect('/index')
    
    return render_template('file_detail.html')

@app.route('/api/file_info')
def api_file_info():
    """获取文件信息API"""
    filename = request.args.get('filename')
    if not filename:
        return jsonify({"status": "error", "message": "未提供文件名"}), 400
    
    # 获取文件路径
    file_path = os.path.join(system_config['upload_folder'], filename)
    
    if not os.path.exists(file_path):
        return jsonify({"status": "error", "message": "文件不存在"}), 404
    
    # 获取文件信息
    file_info = os.stat(file_path)
    
    # 获取元数据
    metadata = load_metadata()
    file_meta = metadata.get(filename, {})
    
    return jsonify({
        "filename": filename,
        "size": file_info.st_size,
        "created": file_info.st_ctime,
        "modified": file_info.st_mtime,
        "download_count": file_meta.get('download_count', 0)
    })


# PDF相关API
@app.route('/api/pdfjs/<path:filename>')
def serve_pdfjs(filename):
    return send_from_directory('static/js/pdf', filename)


# CMAP相关API
@app.route('/api/cmaps/<path:filename>')
def serve_cmaps(filename):
    return send_from_directory('static/cmaps', filename)


# PyPDF PDF信息API
@app.route('/api/pdf_info')
def api_pdf_info():
    """获取PDF文件信息API"""
    filename = request.args.get('filename')
    if not filename:
        return jsonify({"status": "error", "message": "未提供文件名"}), 400
    
    # 获取文件路径
    file_path = os.path.join(system_config['upload_folder'], filename)
    
    if not os.path.exists(file_path):
        return jsonify({"status": "error", "message": "文件不存在"}), 404
    
    try:
        # 导入PyPDF库
        import pypdf
        
        # 打开PDF文件
        with open(file_path, 'rb') as file:
            pdf_reader = PyPDF.PdfReader(file)
            # 获取PDF信息
            num_pages = len(pdf_reader.pages)
            
            # 获取PDF元数据
            metadata = pdf_reader.metadata
            
            return jsonify({
                "status": "success",
                "pages": num_pages,
                "metadata": {
                    "title": metadata.get('/Title', '') if metadata else '',
                    "author": metadata.get('/Author', '') if metadata else '',
                    "subject": metadata.get('/Subject', '') if metadata else '',
                    "creator": metadata.get('/Creator', '') if metadata else '',
                    "producer": metadata.get('/Producer', '') if metadata else '',
                    "creation_date": metadata.get('/CreationDate', '') if metadata else '',
                    "modification_date": metadata.get('/ModDate', '') if metadata else ''
                }
            })
    except Exception as e:
        return jsonify({"status": "error", "message": f"PDF处理失败: {str(e)}"}), 500


# 更新日志页面
@app.route('/changelog')
def changelog():
    return render_template('changelog.html')


# 开源信息页面
@app.route('/open_source')
def open_source():
    return render_template('open_source.html',
                           app_name=system_config['app_name'],
                           app_version=system_config['app_version'],
                           admin_user=system_config['admin_user'],
                           admin_password=system_config['admin_password'])


# 错误管理页面
@app.route('/error_management')
@require_admin_token
def error_management():
    """错误页面管理"""
    return render_template('error_management.html',
                           app_name=system_config['app_name'],
                           app_version=system_config['app_version'])


# 错误页面路由
@app.route('/400')
def error_400():
    """400错误页面"""
    return render_template('400.html')

@app.route('/403')
def error_403():
    """403错误页面"""
    return render_template('403.html')

@app.route('/404')
def error_404():
    """404错误页面"""
    return render_template('404.html')

@app.route('/500')
def error_500():
    """500错误页面"""
    return render_template('500.html')


# 418彩蛋路由
@app.route('/418')
def error_418():
    """418错误页面"""
    return render_template('418.html')

# 错误处理器
@app.errorhandler(400)
def handle_400(error):
    """处理400错误"""
    return render_template('400.html'), 400

@app.errorhandler(403)
def handle_403(error):
    """处理403错误"""
    return render_template('403.html'), 403

@app.errorhandler(404)
def handle_404(error):
    """处理404错误"""
    return render_template('404.html'), 404

@app.errorhandler(500)
def handle_500(error):
    """处理500错误"""
    return render_template('500.html'), 500


# 启动服务
if __name__ == '__main__':
    print("Registered endpoints(API接口):")
    for rule in app.url_map.iter_rules():
        print(f"{rule.endpoint}: {rule}")
    
    init_system()
    
    # 检查更新
    current_version = system_config['app_version']
    update_info = check_for_updates(current_version)
    if update_info:
        print(f"\n\033[92m发现新版本!\033[0m 当前版本: {update_info['current_version']}, 最新版本: {update_info['latest_version']}")
        print(f"下载链接: {update_info['download_url']}")
        print("请访问链接下载并更新到最新版本。\n")
    else:
        print("\n当前已是最新版本。\n")
    
    os.makedirs(system_config['upload_folder'], exist_ok=True)
    os.chmod(system_config['upload_folder'], 0o777)  # 确保可写
    
    print("服务已启动")
    print(f"应用名称: {system_config['app_name']} v{system_config['app_version']}")
    print(f"上传目录: {system_config['upload_folder']}")
    print(f"总空间上限: {convert_size(system_config['max_total_size'] * 1024 * 1024)}")
    print(f"服务启动时间: {SERVICE_START_TIME}")
    print("\n访问地址: http://localhost:" + str(system_config['port']) + "/index")
    print("管理页面: http://localhost:" + str(system_config['port']) + "/admin/login")
    print("纯下载页面: http://localhost:" + str(system_config['port']) + "/")
    print("\033[91m启动后,请到管理员页面配置密码,以生成配置文件")
    print("请管理员尽快到配置文件中配置极验,以便使用离线下载功能\033[0m")

    app.run(host='0.0.0.0', port=system_config['port'], debug=True)
