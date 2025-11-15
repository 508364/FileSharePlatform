"""
更新检测模块
负责检查GitHub上是否有新版本可用
"""

import requests
from requests.adapters import HTTPAdapter
from requests.packages.urllib3.util.retry import Retry
import json
import os

def check_for_updates(current_version):
    """
    检查GitHub上是否有新版本
    
    Args:
        current_version (str): 当前应用版本
    
    Returns:
        dict: 包含更新信息的字典
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
        
        # 版本比较和状态判断
        if latest_version:
            if latest_version > current_version:
                # 有新版本
                download_url = f'https://github.com/{owner}/{repo}/releases/download/FileSharePlatform-v{latest_version}/FileSharePlatform-v{latest_version}.zip'
                proxy_download_url = f'https://ghpxy.hwinzniej.top/{download_url}'
                
                return {
                    'status': 'update_available',
                    'message': '有新版本',
                    'current_version': current_version,
                    'latest_version': latest_version,
                    'download_url': download_url,
                    'proxy_download_url': proxy_download_url,
                    'release_notes': release_info.get('body', ''),
                    'published_at': release_info.get('published_at', ''),
                    'assets': release_info.get('assets', [])
                }
            elif current_version > latest_version:
                # 当前版本高于最新版本（开发版）
                return {
                    'status': 'development_version',
                    'message': '开发版',
                    'current_version': current_version,
                    'latest_version': latest_version,
                    'release_notes': release_info.get('body', ''),
                    'published_at': release_info.get('published_at', '')
                }
            else:
                # 已是最新版本
                return {
                    'status': 'latest_version',
                    'message': '已是最新版本',
                    'current_version': current_version,
                    'latest_version': latest_version,
                    'release_notes': release_info.get('body', ''),
                    'published_at': release_info.get('published_at', '')
                }
        else:
            # 无法获取版本信息
            return {
                'status': 'check_failed',
                'message': '检查失败: 当前已是最新版本',
                'current_version': current_version,
                'latest_version': None
            }
            
    except requests.exceptions.RequestException as e:
        print(f"网络请求错误: {e}")
        return {
            'status': 'check_failed',
            'message': '检查失败: 当前已是最新版本',
            'current_version': current_version,
            'latest_version': None,
            'error': str(e)
        }
    except json.JSONDecodeError as e:
        print(f"JSON解析错误: {e}")
        return {
            'status': 'check_failed',
            'message': '检查失败: 当前已是最新版本',
            'current_version': current_version,
            'latest_version': None,
            'error': str(e)
        }
    except Exception as e:
        print(f"检查更新失败: {e}")
        return {
            'status': 'check_failed',
            'message': '检查失败: 当前已是最新版本',
            'current_version': current_version,
            'latest_version': None,
            'error': str(e)
        }

def get_assets_download_info(assets):
    """
    获取可下载资源信息
    
    Args:
        assets (list): GitHub release的assets列表
    
    Returns:
        dict: 包含不同平台下载链接的字典
    """
    download_info = {}
    
    for asset in assets:
        name = asset.get('name', '').lower()
        download_url = asset.get('browser_download_url', '')
        
        if name.endswith('.exe'):
            download_info['windows'] = download_url
        elif name.endswith('.zip'):
            download_info['source'] = download_url
    
    # 如果没有找到特定平台的安装包，添加默认下载链接
    if not download_info:
        # 使用最后一个asset作为默认下载链接
        if assets:
            download_info['default'] = assets[-1].get('browser_download_url', '')
    
    return download_info