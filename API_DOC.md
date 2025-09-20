# 文件共享平台 API 文档

## 项目介绍
网络文件共享平台是一个基于Flask的Web应用，允许用户上传、下载和管理文件，支持多种文件类型预览，并提供管理员控制面板进行系统配置和管理。

## API 概述
本项目提供RESTful API接口，用于文件操作、系统配置和用户管理等功能。所有API接口均以JSON格式返回数据。

## 基础路径
所有API端点的基础路径为：`/api`

## API 端点详细说明

### 1. 文件操作 API

#### 1.1 上传文件
- **URL**: `/api/upload`
- **方法**: `POST`
- **描述**: 上传单个文件到服务器
- **请求参数**:
  - `file`: 要上传的文件 (form-data)
- **响应**: 
  ```json
  {
    "status": "success",
    "message": "文件上传成功",
    "file_id": "string",
    "file_name": "string",
    "file_size": number
  }
  ```

#### 1.2 多文件上传
- **URL**: `/api/upload/multiple`
- **方法**: `POST`
- **描述**: 上传多个文件到服务器
- **请求参数**:
  - `files`: 要上传的多个文件 (form-data)
- **响应**: 
  ```json
  {
    "status": "success",
    "message": "文件上传成功",
    "files": [
      {
        "file_id": "string",
        "file_name": "string",
        "file_size": number
      }
    ]
  }
  ```

#### 1.3 删除文件
- **URL**: `/api/delete_file`
- **方法**: `POST`
- **描述**: 从服务器删除指定文件
- **请求参数**:
  - `filename`: 要删除的文件名 (JSON)
- **响应**: 
  ```json
  {
    "status": "success",
    "message": "文件删除成功"
  }
  ```

#### 1.4 获取文件列表
- **URL**: `/api/files`
- **方法**: `GET`
- **描述**: 获取服务器上的文件列表
- **响应**: 
  ```json
  {
    "status": "success",
    "files": [
      {
        "name": "string",
        "size": number,
        "mtime": "string",
        "download_count": number
      }
    ]
  }
  ```

### 2. 系统配置 API

#### 2.1 获取系统配置
- **URL**: `/api/system_config`
- **方法**: `GET`
- **描述**: 获取当前系统配置
- **响应**: 
  ```json
  {
    "status": "success",
    "config": {
      "port": number,
      "max_file_size": number,
      "max_total_size": number,
      "network_interface": "string",
      "language": "string"
    }
  }
  ```

#### 2.2 更新系统配置
- **URL**: `/api/update_config`
- **方法**: `POST`
- **描述**: 更新系统配置
- **请求参数** (JSON):
  - `port`: 服务端口
  - `max_file_size`: 最大文件大小 (MB)
  - `max_total_size`: 最大存储空间 (GB)
  - `network_interface`: 网络接口
  - `language`: 界面语言
- **响应**: 
  ```json
  {
    "status": "success",
    "message": "配置更新成功"
  }
  ```

### 3. GitHub 克隆 API

#### 3.1 克隆 GitHub 仓库
- **URL**: `/api/github/clone`
- **方法**: `POST`
- **描述**: 从GitHub克隆仓库到服务器
- **请求参数** (JSON):
  - `repo_url`: GitHub仓库URL
  - `branch`: 分支名称 (可选，默认为main)
- **响应**: 
  ```json
  {
    "status": "success",
    "message": "克隆任务已开始",
    "task_id": "string"
  }
  ```

#### 3.2 获取克隆任务状态
- **URL**: `/api/github/clone/status/<task_id>`
- **方法**: `GET`
- **描述**: 获取GitHub克隆任务的状态
- **响应**: 
  ```json
  {
    "status": "success",
    "task_status": "string", // 可能的值: running, completed, failed
    "progress": number, // 0-100
    "message": "string"
  }
  ```

### 4. 离线下载 API

#### 4.1 创建离线下载任务
- **URL**: `/api/offline_download`
- **方法**: `POST`
- **描述**: 创建离线下载任务
- **请求参数** (JSON):
  - `url`: 下载URL
  - `save_path`: 保存路径 (可选)
- **响应**: 
  ```json
  {
    "status": "success",
    "message": "下载任务已开始",
    "task_id": "string"
  }
  ```

#### 4.2 获取下载任务状态
- **URL**: `/api/offline_download/status/<task_id>`
- **方法**: `GET`
- **描述**: 获取离线下载任务的状态
- **响应**: 
  ```json
  {
    "status": "success",
    "task_status": "string", // 可能的值: running, completed, failed
    "progress": number, // 0-100
    "speed": "string",
    "remaining_time": "string"
  }
  ```

## 错误处理
所有API错误都会返回以下格式的响应：
```json
{
  "status": "error",
  "message": "错误描述"
}
```

常见错误码：
- 400: 请求参数错误
- 401: 未授权
- 403: 权限不足
- 404: 资源不存在
- 500: 服务器内部错误

## 示例代码
### Python 示例 (使用requests库)

#### 上传文件
```python
import requests

url = 'http://localhost:5000/api/upload'
files = {'file': open('example.txt', 'rb')}
response = requests.post(url, files=files)
print(response.json())
```

#### 获取文件列表
```python
import requests

url = 'http://localhost:5000/api/files'
response = requests.get(url)
print(response.json())
```

## 注意事项
1. 文件上传大小限制由服务器配置决定
2. 所有API请求需要根据服务器配置进行身份验证
3. 大文件上传可能需要较长时间，请耐心等待
4. GitHub克隆和离线下载为异步任务，需要通过任务ID查询状态

### 5. 用户组设置 API

#### 5.1 用户注册
- **URL**: `/api/register`
- **方法**: `POST`
- **描述**: 管理员注册新用户
- **请求参数** (JSON):
  - `username`: 用户名
  - `password`: 密码
  - `user_group`: 用户组 (admin/user/guest)
- **响应**: 
  ```json
  {
    "status": "success",
    "message": "用户注册成功"
  }
  ```

#### 5.2 用户登录
- **URL**: `/api/login`
- **方法**: `POST`
- **描述**: 用户登录获取访问令牌
- **请求参数** (JSON):
  - `username`: 用户名
  - `password`: 密码
- **响应**: 
  ```json
  {
    "status": "success",
    "message": "登录成功",
    "token": "string"
  }
  ```

#### 5.3 用户登出
- **URL**: `/api/logout`
- **方法**: `POST`
- **描述**: 用户登出
- **请求参数**: 无
- **响应**: 
  ```json
  {
    "status": "success",
    "message": "登出成功"
  }
  ```

#### 5.4 获取用户组列表
- **URL**: `/api/user_groups`
- **方法**: `GET`
- **描述**: 获取所有用户组及其权限
- **响应**: 
  ```json
  {
    "status": "success",
    "user_groups": [
      {
        "name": "string",
        "permissions": ["string"]
      }
    ]
  }
  ```

#### 5.5 更新用户组权限
- **URL**: `/api/user_groups/<group_name>`
- **方法**: `POST`
- **描述**: 更新指定用户组的权限
- **请求参数** (JSON):
  - `permissions`: 权限列表
- **响应**: 
  ```json
  {
    "status": "success",
    "message": "用户组权限更新成功"
  }
  ```

#### 5.6 获取用户列表
- **URL**: `/api/users`
- **方法**: `GET`
- **描述**: 获取所有用户信息
- **响应**: 
  ```json
  {
    "status": "success",
    "users": [
      {
        "username": "string",
        "user_group": "string",
        "created_at": "string"
      }
    ]
  }
  ```

#### 5.7 更新用户信息
- **URL**: `/api/users/<username>`
- **方法**: `POST`
- **描述**: 更新指定用户的信息
- **请求参数** (JSON):
  - `user_group`: 用户组
- **响应**: 
  ```json
  {
    "status": "success",
    "message": "用户信息更新成功"
  }
  ```

#### 5.8 删除用户
- **URL**: `/api/users/<username>`
- **方法**: `DELETE`
- **描述**: 删除指定用户
- **响应**: 
  ```json
  {
    "status": "success",
    "message": "用户删除成功"
  }
  ```

---
更新时间: 2023-11-07