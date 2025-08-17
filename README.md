
# 文件共享平台 v1.7

***此版更新了更新日志***
[更新日志](./Changelog.md)

基于 Flask 的轻量级文件共享解决方案，支持文件上传、下载、空间管理及系统监控

https://github.com/508364/fileshareplatform

---

## 主要功能

1. **文件管理**
   - 支持拖拽上传/浏览上传
   - 文件大小限制（单文件/总空间）
   - 文件下载计数统计

2. **系统监控**
   - 实时磁盘空间监控
   - 服务器资源监控（CPU/内存/网络）
   - 服务运行状态可视化

3. **安全管理**
   - 管理员权限认证
   - 敏感操作日志记录
   - 文件名安全过滤

4. **扩展性**
   - 模块化代码结构
   - 支持自定义配置
   - 插件式架构设计

---

## 快速开始

### 1. 环境准备

```bash
# 安装依赖库
pip install -r requirements.txt

# 创建虚拟环境（推荐）
python -m venv venv
source venv/bin/activate  # Linux/macOS
venv\Scripts\activate   # Windows
```

### 2. 配置文件

复制并修改配置模板：

```bash
cp fileshare_config.json.example fileshare_config.json
nano fileshare_config.json  # 修改配置参数
```

关键配置项说明：

```json
{
  "max_file_size": 100,      // 单文件最大限制（MB）
  "max_total_size": 1024,    // 总存储空间限制（MB）
  "upload_folder": "uploads",// 文件存储目录
  "admin_user": "admin",     // 管理员账号
  "admin_password": "admin123"// 管理员密码
}
```

### 3. 运行服务

```bash
# 开发模式
export FLASK_ENV=development
flask run --host=0.0.0.0 --port=5000

# 生产模式（推荐使用Gunicorn）
gunicorn --bind 0.0.0.0:5000 server:app
```

### 4. 访问界面

- 主页面：http://localhost:5000/index
- 管理后台：http://localhost:5000/admin
- 开源协议：http://localhost:5000/open_source.html

---

## 高级配置

### 1. 自定义端口

```bash
# 命令行参数
python server.py --port 8080

# 配置文件设置
"port": 8080
```

### 2. 网络接口绑定

```bash
# 绑定特定网卡
python server.py --interface eth0

# 配置文件设置
"network_interface": "eth0"
```

### 3. 日志管理

```bash
# 启用日志记录
export FLASK_LOG_LEVEL=DEBUG

# 日志文件配置
"logging": {
  "level": "INFO",
  "file": "app.log"
}
```

---

## 注意事项

1. **文件权限**：
   ```bash
   chmod 755 uploads/ -R
   chown www-data:www-data uploads/  # Nginx用户组
   ```

2. **安全建议**：
   - 生产环境禁用 DEBUG 模式
   - 定期清理 uploads 目录
   - 使用 HTTPS 加密传输

3. **性能优化**：
   ```bash
   # Gunicorn 生产部署
   gunicorn --workers=4 --threads=2 --timeout=120 server:app
   ```

---

***有时候进入网页无法加载图标是正常的，因为它们需要时间进行缓存，这不会影响正常使用***
---

## 许可协议

本项目采用 MIT 开源，您可以自由使用、修改和分发代码，但需保留原始版权声明。
