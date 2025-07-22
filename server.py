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
from datetime import datetime, timedelta
import re
from flask import Flask, render_template, send_from_directory, request, jsonify, abort, session, redirect, url_for, flash

upload_lock = threading.Lock()

app = Flask(__name__)
app.secret_key = os.urandom(24)  # 添加密钥用于session管理

# 系统配置默认值
DEFAULT_CONFIG = {
    'upload_folder': 'uploads',
    'max_file_size': 100,  # MB
    'max_total_size': 1024,  # MB
    'app_name': '文件共享平台',
    'app_version': '1.2.0',
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
    
    # 确保静态目录存在
    static_dirs = ['static/css', 'static/js']
    for static_dir in static_dirs:
        if not os.path.exists(static_dir):
            os.makedirs(static_dir)
    
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

# 路由处理

# 登录路由
# 先定义/admin路由
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
                           network_interface=system_config['network_interface'])

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

@app.route('/')
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
    print("\n访问地址: http://localhost:5000")
    print("管理页面: http://localhost:5000/admin/login")
    app.run(host='0.0.0.0', port=5000, debug=True)
