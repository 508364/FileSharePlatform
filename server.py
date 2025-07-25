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
import urllib.parse
import urllib.request
import subprocess
import platform
import zipfile
from werkzeug.utils import secure_filename
from datetime import datetime, timedelta
import re
from flask import Flask, render_template, send_from_directory, request, jsonify, abort, session, redirect, url_for, flash
from urllib.parse import urlparse
from urllib3.util.retry import Retry
from requests.adapters import HTTPAdapter
try:
    from json import JSONDecodeError
except ImportError:
    # 对于旧版本Python，从requests库导入
    from requests.exceptions import JSONDecodeError

# 确保json模块有JSONDecodeError属性
if not hasattr(json, 'JSONDecodeError'):
    json.JSONDecodeError = JSONDecodeError

app = Flask(__name__)
app.secret_key = os.urandom(24)  # 添加密钥用于session管理

upload_lock = threading.Lock()

# GitHub镜像克隆队列
github_clone_queue = queue.Queue()
github_clone_tasks = {}
github_clone_lock = threading.Lock()
active_cloners = {} # 当前活跃的克隆任务

# 系统配置默认值
DEFAULT_CONFIG = {
    'upload_folder': 'uploads',
    'max_file_size': 100,  # MB
    'max_total_size': 1024,  # MB
    'app_name': '文件共享平台',
    'app_version': '1.5',
    'admin_user': 'admin',
    'admin_password': 'admin@123',
    'port': 5000,  # 添加端口配置
    'network_interface': 'auto'  # 添加网络接口配置
}

# 系统当前配置
system_config = DEFAULT_CONFIG.copy()

# 配置存储文件
CONFIG_FILE = 'fileshare_config.json'

# 文件元数据存储
METADATA_FILE = 'files_metadata.json'

# 服务启动时间
SERVICE_START_TIME = datetime.now()

# 初始化系统
def init_system():
    # 创建必要目录
    if not os.path.exists(system_config['upload_folder']):
        os.makedirs(system_config['upload_folder'])
    
    # 加载保存的配置
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
                saved_config = json.load(f)
                for key in saved_config:
                    if key in system_config:
                        system_config[key] = saved_config[key]
        except Exception as e:
            print(f"配置加载错误: {e}")
    
    # 确保元数据文件有效
    if not os.path.exists(METADATA_FILE):
        with open(METADATA_FILE, 'w', encoding='utf-8') as f:
            json.dump({}, f, ensure_ascii=False)
    elif os.path.getsize(METADATA_FILE) == 0:  # 修复空文件问题
        with open(METADATA_FILE, 'w', encoding='utf-8') as f:
            json.dump({}, f, ensure_ascii=False)
    
    print("系统初始化完成，元数据文件已就绪")

# 保存配置
def save_config():
    try:
        with open(CONFIG_FILE, 'w', encoding='utf-8') as f:
            json.dump(system_config, f, indent=4, ensure_ascii=False)
    except Exception as e:
        print(f"配置保存失败: {e}")

# 加载文件元数据
def load_metadata():
    # 如果文件不存在或为空，创建有效的JSON文件
    if not os.path.exists(METADATA_FILE) or os.path.getsize(METADATA_FILE) == 0:
        try:
            with open(METADATA_FILE, 'w', encoding='utf-8') as f:
                json.dump({}, f, ensure_ascii=False)  # 创建有效的空JSON
            return {}
        except Exception as e:
            print(f"元数据文件创建失败: {e}")
            return {}
    
    try:
        with open(METADATA_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    except json.JSONDecodeError:
        print("元数据文件格式错误，重置中...")
        try:
            with open(METADATA_FILE, 'w', encoding='utf-8') as f:
                json.dump({}, f, ensure_ascii=False)  # 重置为有效JSON
            return {}
        except Exception as e:
            print(f"元数据重置失败: {e}")
            return {}
    except Exception as e:
        print(f"元数据加载错误: {e}")
        return {}

# 更新文件元数据
def update_metadata(filename, action='upload'):
    metadata = load_metadata()
    file_path = os.path.join(system_config['upload_folder'], filename)
    
    if not os.path.exists(file_path):
        return None
    
    # 获取文件属性
    stat = os.stat(file_path)
    file_size = stat.st_size
    file_mtime = stat.st_mtime
    file_ctime = stat.st_ctime
    
    # 初始化文件元数据
    if filename not in metadata:
        metadata[filename] = {
            'size': file_size,
            'created': file_ctime,
            'modified': file_mtime,
            'download_count': 0
        }
    
    # 更新元数据
    if action == 'download':
        metadata[filename]['download_count'] += 1
    elif action == 'upload':
        metadata[filename]['size'] = file_size
        metadata[filename]['modified'] = file_mtime
    
    # 保存元数据
    try:
        with open(METADATA_FILE, 'w', encoding='utf-8') as f:
            json.dump(metadata, f, indent=4, ensure_ascii=False)
    except Exception as e:
        print(f"元数据保存失败: {e}")
    
    return metadata[filename]

# 获取文件列表
def get_file_list():
    upload_dir = system_config['upload_folder']
    if not os.path.exists(upload_dir):
        return []
    
    metadata = load_metadata()
    files = []
    
    for filename in os.listdir(upload_dir):
        file_path = os.path.join(upload_dir, filename)
        if os.path.isfile(file_path):
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
    
    # 按修改时间排序（最新在上）
    files.sort(key=lambda x: x['modified'], reverse=True)
    return files

# 获取磁盘空间使用情况
def get_disk_usage():
    upload_dir = system_config['upload_folder']
    
    # 确保上传目录存在
    if not os.path.exists(upload_dir):
        os.makedirs(upload_dir)
    
    # 获取上传目录使用情况
    upload_usage = 0
    for entry in os.scandir(upload_dir):
        if entry.is_file():
            upload_usage += entry.stat().st_size
    
    max_total_bytes = system_config['max_total_size'] * 1024 * 1024
    
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
        usage_percent = min(100, int((upload_usage / max_total_bytes) * 100))
    
    return {
        'system_total': total,
        'system_used': used,
        'system_free': free,
        'upload_total': max_total_bytes,
        'upload_used': upload_usage,
        'available': min(max_total_bytes - upload_usage, free),
        'usage_percent': usage_percent
    }

# 添加认证中间件
def require_admin_token(func):
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

# 获取系统资源信息
def get_system_resources():
    try:
        # CPU使用率
        cpu_percent = psutil.cpu_percent(interval=1)
        
        # 内存使用率
        mem = psutil.virtual_memory()
        mem_percent = mem.percent
        mem_total = mem.total
        mem_used = mem.used
        
        # 网络接口
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
            'mem_percent': '获取系统资源失败',
            'mem_total': '获取系统资源失败',
            'mem_used': '获取系统资源失败',
            'interfaces': [
                {'interface': '本地连接', 'ip': '127.0.0.1'}
            ]
        }

# 检查Git是否安装
def is_git_installed():
    try:
        result = subprocess.run(['git', '--version'], capture_output=True, text=True, timeout=5)
        return result.returncode == 0
    except:
        return False

# 安装Git（仅Windows）
def install_git():
    if platform.system() != 'Windows':
        return False
    
    try:
        result = subprocess.run(['winget', 'install', '--id', 'Git.Git', '-e', '--source', 'winget'], 
                                capture_output=True, text=True, timeout=300)
        return result.returncode == 0
    except:
        return False

# GitHub仓库克隆器
class GitHubCloner:
    def __init__(self, repo_url, task_id, branch="main"):
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
        """从仓库URL提取仓库名称"""
        if self.repo_url.endswith('.git'):
            repo_url = self.repo_url[:-4]
        else:
            repo_url = self.repo_url
        
        if repo_url.endswith('/'):
            repo_url = repo_url[:-1]
        
        return repo_url.split('/')[-1]
    
    def clone(self):
        """执行仓库克隆任务"""
        try:
            self.status = "cloning"
            
            # 获取仓库名称
            repo_name = self.get_repo_name()
            self.clone_dir = os.path.join(self.temp_dir, repo_name)
            
            # 创建文件夹名称
            folder_name = f"{repo_name}-{self.branch}"
            counter = 1
            while os.path.exists(os.path.join(self.temp_dir, folder_name)):
                folder_name = f"{repo_name}-{self.branch}_{counter}"
                counter += 1
            
            self.clone_dir = os.path.join(self.temp_dir, folder_name)
            
            # 执行git clone命令
            cmd = ['git', 'clone', '--branch', self.branch, self.repo_url, self.clone_dir]
            self.process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True
            )
            
            # 监控克隆进度
            while True:
                if self.cancelled:
                    raise RuntimeError("任务已被取消")
                
                # 检查进程是否完成
                if self.process.poll() is not None:
                    break
                
                # 简单模拟进度更新
                self.progress = min(99, self.progress + 1)
                time.sleep(0.5)
            
            # 检查命令执行结果
            if self.process.returncode != 0:
                error_output = self.process.stderr.read()
                raise RuntimeError(f"Git克隆失败: {error_output}")
            
            # 打包仓库（排除.git目录）
            self.package_repo(folder_name)
            
            # 移动到上传目录
            self.move_to_uploads()
            
            # 更新状态
            self.status = "completed"
        
        except Exception as e:
            self.status = "failed"
            self.error = str(e)
        
        finally:
            # 清理临时目录
            if os.path.exists(self.temp_dir):
                shutil.rmtree(self.temp_dir, ignore_errors=True)
    
    def package_repo(self, folder_name):
        """将仓库打包为ZIP文件"""
        try:
            # 创建ZIP文件
            self.file_name = f"{folder_name}.zip"
            self.zip_path = os.path.join(self.temp_dir, self.file_name)
            
            # 创建ZIP文件
            with zipfile.ZipFile(self.zip_path, 'w', zipfile.ZIP_DEFLATED) as zipf:
                for root, dirs, files in os.walk(self.clone_dir):
                    # 排除.git目录
                    if '.git' in dirs:
                        dirs.remove('.git')
                    
                    for file in files:
                        file_path = os.path.join(root, file)
                        arcname = os.path.relpath(file_path, self.clone_dir)
                        zipf.write(file_path, arcname)
        except Exception as e:
            raise RuntimeError(f"打包失败: {str(e)}")
    
    def move_to_uploads(self):
        """将ZIP文件移动到上传目录"""
        upload_dir = system_config['upload_folder']
        final_path = os.path.join(upload_dir, self.file_name)
        
        # 处理重名文件
        counter = 1
        name, ext = os.path.splitext(self.file_name)
        while os.path.exists(final_path):
            new_name = f"{name}_{counter}{ext}"
            final_path = os.path.join(upload_dir, new_name)
            counter += 1
        
        shutil.move(self.zip_path, final_path)
        self.final_path = final_path
        
        # 更新元数据
        update_metadata(os.path.basename(final_path), 'upload')
        
        # 添加来源信息
        metadata = load_metadata()
        if self.file_name in metadata:
            metadata[self.file_name]['source'] = {
                "type": "github",
                "repo_url": self.repo_url,
                "branch": self.branch,
                "cloned_at": time.strftime("%Y-%m-%d %H:%M:%S")
            }
            
            try:
                with open(METADATA_FILE, 'w', encoding='utf-8') as f:
                    json.dump(metadata, f, indent=4, ensure_ascii=False)
            except Exception as e:
                print(f"元数据保存失败: {e}")
    
    def cancel(self):
        """取消克隆任务"""
        self.cancelled = True
        if self.process and self.process.poll() is None:
            self.process.terminate()
            try:
                self.process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.process.kill()

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
                
                cloner.clone()
                
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
upload_lock = threading.Lock()

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

# 路由处理

# 登录路由
# 定义admin路由
@app.route('/admin')
def admin():
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
    return render_template('admin.html',
                           disk_space=disk_space,
                           files=files,
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
                           offline_download_enabled=True)

# 定义/admin/login路由（合并GET和POST）
@app.route('/admin/login', methods=['GET', 'POST'], endpoint='admin_login')
def admin_login():
    if request.method == 'GET':
        return render_template('admin_login.html')
    else:
        data = request.get_json()
        if data.get('username') == system_config['admin_user'] and \
           data.get('password') == system_config['admin_password']:
            session_token = os.urandom(24).hex()
            session['admin_token'] = session_token
            return jsonify({"status": "success", "token": session_token})
        return jsonify({"status": "error", "message": "无效凭据"}), 401

@app.route('/index')
def index():
    disk = get_disk_usage()
    files = get_file_list()
    
    return render_template('index.html',
                           files=files,
                           app_name=system_config['app_name'],
                           total_space=convert_size(disk['upload_total']),
                           used_space=convert_size(disk['upload_used']),
                           free_space=convert_size(disk['available']),
                           max_file_size=system_config['max_file_size'],
                           usage_percent=disk['usage_percent'])

@app.route('/open_source')
def open_source():
    return render_template('open_source.html',
                           app_name=system_config['app_name'],
                           app_version=system_config['app_version'],
                           admin_user=system_config['admin_user'],
                           admin_password=system_config['admin_password'])

@app.route('/static/<path:filename>')
def static_files(filename):
    return send_from_directory('static', filename)

# 第一个admin_login函数，添加endpoint参数
@app.route('/admin/login', methods=['POST'], endpoint='admin_login_post')
def admin_login():
    data = request.get_json()
    if data.get('username') == system_config['admin_user'] and \
       data.get('password') == system_config['admin_password']:
        # 创建会话令牌
        session_token = os.urandom(24).hex()
        session['admin_token'] = session_token
        return jsonify({"status": "success", "token": session_token})
    return jsonify({"status": "error", "message": "无效凭据"}), 401

# 第二个admin_login函数，添加endpoint参数
@app.route('/admin/login', methods=['GET'], endpoint='admin_login_get')
def admin_login():
    if request.method == 'GET':
        # 直接渲染登录模板
        return render_template('admin_login.html')

# 添加登出功能
@app.route('/admin/logout')
def admin_logout():
    session.pop('admin_token', None)
    return redirect('/admin/login')

@app.route('/admin/github_clone')
def admin_operations():
    # 检查管理员登录状态
    if 'admin_token' not in session:
        return redirect('/admin/login')
    
    # 获取磁盘使用情况
    disk = get_disk_usage()
    
    # 获取文件列表
    files = get_file_list()
    
    return render_template('github_clone.html',
                           files=files,
                           disk=disk,
                           max_file_size=system_config['max_file_size'],
                           max_total_size=system_config['max_total_size'],
                           upload_folder=system_config['upload_folder'])

# API接口
@app.route('/api/files')
def api_files():
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
            # 添加 hash 字段（这里用文件名代替）
            'hash': file['name']  
        })
    
    return jsonify({
        'files': formatted_files,
        'disk_used': disk['upload_used'],
        'max_storage': system_config['max_total_size'] * 1024 * 1024
    })

@app.route('/api/sysinfo')
def api_sysinfo():
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

# 配置更新API
@app.route('/api/update_config', methods=['POST'], endpoint='update_config')
@require_admin_token
def api_update_config():
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

@app.route('/api/upload', methods=['POST'])

def upload():
    if 'file' not in request.files:
        return jsonify({"status": "error", "message": "未选择文件"})
    
    file = request.files['file']
    
    # 验证文件名
    if not file.filename or '.' not in file.filename:
        return jsonify({"status": "error", "message": "无效的文件名"})
    
    # 获取文件大小（更可靠的方法）
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
    
    # 检查总空间（更严格的检查）
    disk = get_disk_usage()
    if file_size > disk['available']:
        return jsonify({
            "status": "error",
            "message": f"磁盘空间不足（可用空间：{convert_size(disk['available'])}）"
        })
    
    # 添加全局上传锁，防止并发上传导致空间超限
    with upload_lock:
        # 再次检查空间（防止在检查期间有其他文件上传）
        disk = get_disk_usage()
        if file_size > disk['available']:
            return jsonify({
                "status": "error",
                "message": "空间不足，请稍后再试"
            })
        
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
            return jsonify({"status": "error", "message": f"保存失败: {str(e)}"})

@app.route('/api/system/config')
def get_system_config():
    return jsonify({
        'max_file_size': system_config['max_file_size'],
        'max_total_size': system_config['max_total_size'],
        'app_name': system_config['app_name'],
        'app_version': system_config['app_version']
    })

@app.route('/download/<filename>')
def download(filename):
    if '../' in filename or not re.match(r'^[\w\-. ]+$', filename):
        abort(400)

    upload_dir = system_config['upload_folder']
    file_path = os.path.join(upload_dir, filename)
    
    if not os.path.isfile(file_path):
        abort(404)
    
    update_metadata(filename, 'download')
    return send_from_directory(upload_dir, filename, as_attachment=True)

# 实用功能
def convert_size(size_bytes):
    """根据文件大小自动选择合适的单位"""
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

def secure_filename(filename):
    """安全处理文件名"""
    # 基本清理功能
    keep = (' ', '.', '_')
    cleaned = ''.join(c for c in filename if c.isalnum() or c in keep).rstrip()
    return cleaned or 'file'

@app.route('/space')
def space_info():
    disk = get_disk_usage()
    return f"""
    总空间: {convert_size(disk['upload_total'])}
    已使用: {convert_size(disk['upload_used'])}
    可用空间: {convert_size(disk['available'])}
    使用率: {disk['usage_percent']}%
    """
@app.route('/admin/change_password', methods=['POST'])
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

@app.route('/api/delete_file', methods=['POST'], endpoint='api_delete_file')
@require_admin_token
def api_delete_file():
    try:
        # 从JSON数据获取文件名
        data = request.get_json()
        filename = data.get('filename')
        
        if not filename:
            return jsonify({"status": "error", "message": "文件名不能为空"}), 400
        
        file_path = os.path.join(system_config['upload_folder'], filename)
        
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

# GitHub镜像克隆
@app.route('/api/github_clone', methods=['POST'])
def add_github_clone():
    if 'admin_token' not in session:
        return jsonify({"status": "error", "message": "未授权访问"}), 403
    
    # 检查Git是否安装
    if not is_git_installed():
        # 尝试安装Git（仅Windows）
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
    if 'admin_token' not in session:
        return jsonify({"status": "error", "message": "未授权访问"}), 403
    
    with github_clone_lock:
        return jsonify({
            "tasks": github_clone_tasks,
            "active_count": github_clone_queue.qsize(),
            "thread_active": github_clone_thread.is_alive()
        })

@app.route('/api/github_clone/cancel_task', methods=['POST'])
def cancel_github_clone_task():
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
            # 如果任务不在活动状态，但存在于任务列表中
            github_clone_tasks[task_id]['status'] = 'cancelled'
            return jsonify({"status": "success", "message": "任务已标记为取消"})
        else:
            return jsonify({"status": "error", "message": "任务不存在"}), 404

@app.route('/api/github_clone/clear_tasks', methods=['POST'])
def clear_github_clone_tasks():
    if 'admin_token' not in session:
        return jsonify({"status": "error", "message": "未授权访问"}), 403
    
    data = request.get_json()
    clear_type = data.get('type', 'completed')  # 默认清除已完成任务
    
    with github_clone_lock:
        # 根据类型清除任务
        tasks_to_remove = []
        for task_id, task in list(github_clone_tasks.items()):
            if clear_type == 'all':
                tasks_to_remove.append(task_id)
            elif clear_type == 'completed' and task['status'] == 'completed':
                tasks_to_remove.append(task_id)
            elif clear_type == 'failed' and task['status'] == 'failed':
                tasks_to_remove.append(task_id)
            elif clear_type == 'cancelled' and task['status'] == 'cancelled':
                tasks_to_remove.append(task_id)
        
        # 移除选中的任务
        for task_id in tasks_to_remove:
            del github_clone_tasks[task_id]
        
        return jsonify({
            "status": "success",
            "removed_count": len(tasks_to_remove),
            "remaining_count": len(github_clone_tasks)
        })

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

# 获取磁盘空间信息API
@app.route('/api/sysinfo', methods=['GET'])
def get_sysinfo():
    # 计算上传目录使用情况
    upload_dir = system_config['upload_folder']
    upload_usage = 0
    
    if os.path.exists(upload_dir):
        for entry in os.scandir(upload_dir):
            if entry.is_file():
                upload_usage += entry.stat().st_size
    
    max_total_bytes = system_config['max_total_size'] * 1024 * 1024
    
    return jsonify({
        "disk": {
            "upload_used": upload_usage,
            "available": max_total_bytes - upload_usage
        },
        "config": {
            "max_file_size": system_config['max_file_size']
        }
    })

# 文件下载中心页面路由
@app.route('/')
def download_page():
    """文件下载中心页面"""
    return render_template('download_page.html')

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

@app.route('/changelog')
def changelog():
    return render_template('changelog.html')

# 启动服务
if __name__ == '__main__':
    print("Registered endpoints(API接口):")
    for rule in app.url_map.iter_rules():
        print(f"{rule.endpoint}: {rule}")
    init_system()
    os.makedirs(system_config['upload_folder'], exist_ok=True)
    os.chmod(system_config['upload_folder'], 0o777)  # 确保可写
    print("服务已启动")
    print(f"应用名称: {system_config['app_name']} v{system_config['app_version']}")
    print(f"上传目录: {system_config['upload_folder']}")
    print(f"总空间上限: {convert_size(system_config['max_total_size'] * 1024 * 1024)}")
    print(f"服务启动时间: {SERVICE_START_TIME}")
    print("\n访问地址: http://localhost:" +  str(system_config['port']) + "/index")
    print("管理页面: http://localhost:" + str(system_config['port']) + "/admin/login")
    print("纯下载页面: http://localhost:" + str(system_config['port']) + "/")
    app.run(host='0.0.0.0', port=system_config['port'], debug=True)
