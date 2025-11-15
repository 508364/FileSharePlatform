"""
FileSharePlatform 更新模块
用于处理系统在线更新的所有功能
"""

from .update_check import check_for_updates
from .update_download import download_update
from .update_restart import restart_server
from .update_utils import get_current_version, log_update

__all__ = ['check_for_updates', 'download_update', 'restart_server', 'get_current_version', 'log_update']