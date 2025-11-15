"""
服务器重启模块
负责安全地重启服务器应用
"""

import os
import signal
import subprocess
import time
import sys
from pathlib import Path

# 服务器主进程文件路径
SERVER_SCRIPT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'server.py')

def get_server_process():
    """
    获取当前运行的服务器进程
    
    Returns:
        subprocess.Popen or None: 服务器进程对象，如果未找到则返回None
    """
    try:
        # 尝试通过进程名查找server.py
        import psutil
        
        for proc in psutil.process_iter(['pid', 'name', 'cmdline']):
            try:
                cmdline = proc.info['cmdline']
                if cmdline and any('server.py' in str(cmd) for cmd in cmdline):
                    return proc
            except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
                continue
        
        return None
    except ImportError:
        # 如果psutil不可用，尝试其他方法
        return None
    except Exception as e:
        print(f"查找服务器进程时发生错误: {e}")
        return None

def safe_shutdown():
    """
    安全关闭当前服务器进程
    
    Returns:
        bool: 是否成功关闭
    """
    try:
        proc = get_server_process()
        if proc:
            print(f"发送SIGTERM信号到进程 {proc.pid}")
            proc.terminate()
            
            # 等待进程结束，最多等待30秒
            try:
                proc.wait(timeout=30)
                print("服务器进程已安全关闭")
                return True
            except psutil.TimeoutExpired:
                print("等待进程结束超时，强制结束")
                proc.kill()
                return True
        else:
            print("未找到正在运行的服务器进程")
            return True
            
    except Exception as e:
        print(f"关闭服务器进程时发生错误: {e}")
        return False

def restart_server():
    """
    重启服务器
    
    Returns:
        bool: 是否成功启动新进程
    """
    try:
        # 检查服务器脚本是否存在
        if not os.path.exists(SERVER_SCRIPT):
            print(f"服务器脚本不存在: {SERVER_SCRIPT}")
            return False
        
        # 获取当前工作目录
        cwd = os.path.dirname(SERVER_SCRIPT)
        
        # 启动新进程
        print("启动新服务器进程...")
        
        if sys.platform.startswith('win'):
            # Windows平台
            creationflags = subprocess.CREATE_NEW_CONSOLE
            startupinfo = subprocess.STARTUPINFO()
            startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            startupinfo.wShowWindow = subprocess.SW_HIDE
        else:
            # Unix/Linux平台
            creationflags = 0
            startupinfo = None
        
        # 启动新进程
        subprocess.Popen([
            sys.executable, SERVER_SCRIPT
        ], cwd=cwd, creationflags=creationflags, startupinfo=startupinfo)
        
        print("新服务器进程已启动")
        return True
        
    except Exception as e:
        print(f"重启服务器时发生错误: {e}")
        return False

def restart_with_update():
    """
    应用更新并重启服务器
    
    Returns:
        bool: 是否成功重启
    """
    try:
        print("开始执行服务器重启...")
        
        # 关闭当前进程
        if not safe_shutdown():
            print("关闭服务器失败")
            return False
        
        # 等待一段时间确保进程完全关闭
        time.sleep(2)
        
        # 启动新进程
        if not restart_server():
            print("启动新服务器失败")
            return False
        
        print("服务器重启完成")
        return True
        
    except Exception as e:
        print(f"重启过程中发生错误: {e}")
        return False

def get_system_info():
    """
    获取系统信息用于重启日志
    
    Returns:
        dict: 系统信息
    """
    import platform
    
    return {
        'platform': platform.system(),
        'platform_version': platform.version(),
        'python_version': sys.version,
        'server_script': SERVER_SCRIPT,
        'current_working_dir': os.getcwd()
    }