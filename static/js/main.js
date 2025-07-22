document.addEventListener('DOMContentLoaded', () => {
    // 全局变量
    let fileData = [];
    let uploadProgress = 0;
    let startTime = new Date().toISOString();

    const API_BASE = 'http://localhost:5000';

    // 页面加载时加载文件列表
    // 修改后的 loadFiles 函数
function loadFiles() {
    document.getElementById('file-list').innerHTML = `
        <div class="col-12 text-center py-5" id="loading-files">
            <div class="spinner-border text-primary" role="status">
                <span class="visually-hidden">加载中...</span>
            </div>
            <p class="mt-2">正在加载文件列表...</p>
        </div>
    `;
    
    fetch(`${API_BASE}/api/files`)
        .then(res => res.json())
        .then(data => {
            // 修复1：使用正确的后端返回字段名
            const diskUsed = data.disk_used || data.upload_used;
            const maxStorage = data.max_storage || (system_config?.max_total_size * 1024 * 1024);
            
            // 更新存储空间信息
            document.getElementById('disk-used').textContent = formatBytes(diskUsed);
            document.getElementById('max-storage').textContent = formatBytes(maxStorage);
            const usagePercent = Math.round((diskUsed / maxStorage) * 100);
            document.getElementById('usage-percent').textContent = `${usagePercent}%`;
            document.getElementById('storage-progress').style.width = `${usagePercent}%`;
            
            // 渲染文件列表
            if (!data.files || data.files.length === 0) {
                document.getElementById('file-list').innerHTML = `
                    <div class="col-12 text-center py-5">
                        <i class="bi bi-folder-x display-4 text-muted mb-3"></i>
                        <h5 class="text-muted">暂无文件</h5>
                        <p>上传第一个文件开始使用</p>
                    </div>
                `;
                return;
            }
            
            let html = '';
            data.files.forEach(file => {
                // 修复2：直接使用后端返回的时间戳（已经是毫秒）
                const fileDate = new Date(file.modified || file.created);
                const displayDate = fileDate.toLocaleDateString();
                
                // 修复3：统一使用filename字段
                const fileName = file.filename || file.name || "未命名文件";
                const fileSize = file.size || 0;
                const downloadLink = `/download/${encodeURIComponent(fileName)}`;
                
                html += `
                    <div class="col-md-6 col-lg-4 col-xl-3">
                        <div class="card file-card">
                            <div class="card-body">
                                <div class="file-icon text-primary">
                                    <i class="bi ${getFileIcon(getFileType(fileName))}"></i>
                                </div>
                                <h6 class="card-title text-truncate" title="${fileName}">${fileName}</h6>
                                <div class="d-flex justify-content-between small text-muted mb-2">
                                    <span>${formatBytes(fileSize)}</span>
                                    <span>${displayDate}</span>
                                </div>
                                <div class="d-flex justify-content-between align-items-center mt-3">
                                    <a href="${downloadLink}" class="btn btn-sm btn-outline-primary">
                                        <i class="bi bi-download me-1"></i>下载
                                    </a>
                                    <span class="text-muted small">
                                        <i class="bi bi-arrow-down-circle"></i> ${file.download_count || 0}
                                    </span>
                                </div>
                            </div>
                        </div>
                    </div>
                `;
            });
            
            document.getElementById('file-list').innerHTML = html;
        })
        .catch(error => {
            console.error('加载文件列表失败:', error);
            document.getElementById('file-list').innerHTML = `
                <div class="col-12 text-center py-5">
                    <i class="bi bi-exclamation-triangle display-4 text-danger mb-3"></i>
                    <h5 class="text-danger">加载失败</h5>
                    <p>无法获取文件列表，请刷新重试</p>
                </div>
            `;
        });
}
    
    // 渲染文件列表
    function renderFileList() {
        const fileList = document.getElementById('file-list');
        fileList.innerHTML = '';
        
        fileData.forEach(file => {
            const fileCard = document.createElement('div');
            fileCard.className = 'col-md-3 mb-4';
            fileCard.innerHTML = `
                <div class="card h-100 file-card">
                    <div class="card-body">
                        <div class="d-flex justify-content-between align-items-center mb-2">
                            <h6 class="card-title mb-0">${file.name}</h6>
                            <span class="badge bg-secondary fs-6">${getFileExtension(file.name)}</span>
                        </div>
                        <div class="d-flex flex-column">
                            <small class="text-muted mb-1">大小: ${convertSize(file.size)}</small>
                            <small class="text-muted mb-2">上传于: ${formatDate(file.modified)}</small>
                        </div>
                    </div>
                    <div class="card-footer bg-transparent d-flex justify-content-between">
                        <small class="text-muted">下载: ${file.download_count}次</small>
                        <button onclick="downloadFile('${file.name}')" class="btn btn-sm btn-primary">下载</button>
                    </div>
                </div>
            `;
            fileList.appendChild(fileCard);
        });
    }
    
    // 加载系统配置
    function loadSystemConfig() {
        fetch('/api/sysinfo')
            .then(response => response.json())
            .then(data => {
                const disk = data.disk;
                const config = data.config;
                
                // 更新主页面磁盘信息
                if(document.getElementById('disk-progress')) {
                    document.getElementById('disk-progress').style.width = `${disk.usage_percent}%`;
                    document.getElementById('disk-text').innerText = `已用 ${convertSize(disk.upload_used)} / ${convertSize(disk.upload_total)}`;
                    document.getElementById('free-space').innerText = `剩余 ${convertSize(disk.available)}`;
                }
                
                // 更新管理页面配置
                if(document.getElementById('maxFileSize')) {
                    document.getElementById('maxFileSize').value = config.max_file_size;
                    document.getElementById('maxTotalSize').value = config.max_total_size;
                    
                    // 更新管理页面磁盘使用情况
                    document.getElementById('systemTotal').innerText = convertSize(disk.system_total);
                    document.getElementById('systemUsed').innerText = convertSize(disk.system_used);
                    document.getElementById('uploadUsed').innerText = convertSize(disk.upload_used);
                    document.getElementById('uploadTotal').innerText = convertSize(disk.upload_total);
                    
                    // 更新运行时间
                    document.getElementById('uptime').innerText = `服务自 ${formatDate(new Date(startTime))} 运行至今`;
                }
            })
            .catch(error => console.error('加载系统配置失败:', error));
    }
    
    // 配置更新处理
    function updateSystemConfig() {
        const maxFileSize = document.getElementById('maxFileSize').value;
        const maxTotalSize = document.getElementById('maxTotalSize').value;
        
        if(!maxFileSize || !maxTotalSize) {
            alert('请填写所有配置项');
            return;
        }
        
        fetch('/api/update_config', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify({
                maxFileSize: parseInt(maxFileSize),
                maxTotalSize: parseInt(maxTotalSize)
            })
        })
        .then(response => response.json())
        .then(data => {
            if(data.status === 'success') {
                alert('配置更新成功！');
                loadSystemConfig();
            } else {
                alert(`配置更新失败: ${data.message}`);
            }
        })
        .catch(error => {
            console.error('配置更新失败:', error);
            alert('配置更新失败，请检查网络连接');
        });
    }
    
    // 上传文件
    function uploadFile(file) {
        // 获取最大文件大小限制（从系统配置）
        const maxFileSize = parseInt(systemConfig.max_file_size) * 1024 * 1024;
    
        // 检查文件大小
        if (file.size > maxFileSize) {
            alert(`文件大小超过限制（最大${formatBytes(maxFileSize)}）`);
            resetUploadUI();
            return;
        }

        if(!file) return;
        
        const formData = new FormData();
        formData.append('file', file);
        
        const xhr = new XMLHttpRequest();
        
        // 进度处理
        xhr.upload.addEventListener('progress', (e) => {
            if (e.lengthComputable) {
                const percent = Math.round((e.loaded / e.total) * 100);
                uploadProgress = percent;
                document.getElementById('upload-progress').style.width = `${percent}%`;
                document.getElementById('upload-text').innerText = `${percent}%`;
            }
        });
        
        // 完成处理
        xhr.addEventListener('load', () => {
    if (xhr.status >= 200 && xhr.status < 300) {
        // 上传成功处理
    } else {
        try {
            const err = JSON.parse(xhr.response);
            let errorMsg = '上传失败';
            
            if (err.message) {
                errorMsg = err.message;
            } else if (xhr.status === 413) {
                errorMsg = '文件太大，超过系统限制';
            } else if (xhr.status === 507) {
                errorMsg = '磁盘空间不足';
            }
            
            uploadStats.innerHTML = `<span class="text-danger"><i class="bi bi-exclamation-circle-fill"></i> ${errorMsg}</span>`;
        } catch (e) {
            uploadStats.innerHTML = `<span class="text-danger"><i class="bi bi-exclamation-circle-fill"></i> 上传失败</span>`;
        }
    }
});
        
        // 错误处理
        xhr.addEventListener('error', () => {
            alert('上传过程中发生错误');
        });
        
        xhr.open('POST', '/api/upload');
        xhr.send(formData);
    }
    
    // 绑定事件监听器
    function initEventListeners() {
        // 文件输入变化时触发上传
        document.getElementById('fileInput')?.addEventListener('change', (e) => {
            if(e.target.files.length > 0) {
                uploadFile(e.target.files[0]);
            }
        });
        
        // 管理员页面保存按钮
        document.getElementById('save-config')?.addEventListener('click', updateSystemConfig);
        
        // 拖拽上传处理
        const dropArea = document.getElementById('drop-area');
        if(dropArea) {
            dropArea.addEventListener('dragover', (e) => {
                e.preventDefault();
                dropArea.classList.add('drag-over');
            });
            
            dropArea.addEventListener('dragleave', () => {
                dropArea.classList.remove('drag-over');
            });
            
            dropArea.addEventListener('drop', (e) => {
                e.preventDefault();
                dropArea.classList.remove('drag-over');
                
                if(e.dataTransfer.files.length > 0) {
                    uploadFile(e.dataTransfer.files[0]);
                }
            });
        }
    }
    
    // 工具函数：获取文件扩展名
    function getFileExtension(filename) {
        return filename.split('.').pop().toUpperCase();
    }
    
    // 工具函数：格式化日期
    function formatDate(timestamp) {
        const date = new Date(timestamp);
        return date.toLocaleDateString();
    }
    
    // 工具函数：转换文件大小
    function convertSize(size) {
        if (size < 1024) return `${size} B`;
        if (size < 1024 * 1024) return `${(size / 1024).toFixed(2)} KB`;
        if (size < 1024 * 1024 * 1024) return `${(size / (1024 * 1024)).toFixed(2)} MB`;
        return `${(size / (1024 * 1024 * 1024)).toFixed(2)} GB`;
    }
    
    // 下载文件
    window.downloadFile = function(filename) {
        // 创建下载链接
        const link = document.createElement('a');
        link.href = `/download/${encodeURIComponent(filename)}`;
        link.download = filename;
        document.body.appendChild(link);
        link.click();
        document.body.removeChild(link);
        
        // 更新文件列表
        setTimeout(() => {
            loadFiles();
            loadSystemConfig();
        }, 1000);
    }
    
    // 初始化页面
    loadFiles();
    loadSystemConfig();
    initEventListeners();
    
    // 每隔10秒刷新状态
    setInterval(loadSystemConfig, 10000);
});

// 格式化字节大小为易读格式
function formatBytes(bytes) {
    if (bytes === 0) return '0B';
    
    const units = ['B', 'KB', 'MB', 'GB', 'TB'];
    const i = Math.floor(Math.log(bytes) / Math.log(1024));
    const size = bytes / Math.pow(1024, i);
    
    // 根据大小选择合适的精度
    if (size < 10) {
        return size.toFixed(2) + ' ' + units[i];
    } else if (size < 100) {
        return size.toFixed(1) + ' ' + units[i];
    } else {
        return size.toFixed(0) + ' ' + units[i];
    }
}

// 更新系统状态显示
function updateSystemStatus() {
    fetch('/api/sysinfo')
        .then(response => response.json())
        .then(data => {
            // 更新磁盘使用情况
            document.getElementById('stat-files').textContent = data.file_count;
            document.getElementById('stat-downloads').textContent = data.total_downloads;
            
            const usagePercent = Math.round((data.disk.upload_used / data.disk.upload_total) * 100);
            document.getElementById('stat-usage').textContent = `${usagePercent}%`;
            
            // 更新运行时间
            const uptime = new Date(data.uptime);
            document.getElementById('stat-uptime').textContent = 
                `${uptime.getUTCHours()}h ${uptime.getUTCMinutes()}m ${uptime.getUTCSeconds()}s`;
            
            // 更新存储配置
            document.getElementById('max-storage').value = data.config.max_total_size;
            document.getElementById('max-file-size').value = data.config.max_file_size;
            
            // 更新存储使用情况
            document.getElementById('current-usage').textContent = formatBytes(data.disk.upload_used);
            document.getElementById('available-storage').textContent = formatBytes(data.disk.available);
            
            // 更新进度条
            document.getElementById('usage-bar').style.width = `${usagePercent}%`;
        })
        .catch(error => console.error('Error fetching system status:', error));
}

// 初始化页面
document.addEventListener('DOMContentLoaded', () => {
    // 设置定时器定期更新状态
    setInterval(updateSystemStatus, 5000);
    
    // 初始更新
    updateSystemStatus();
    
    // 配置更新表单提交
    document.getElementById('storage-config-form').addEventListener('submit', async (e) => {
        e.preventDefault();
        
        const maxStorage = parseInt(document.getElementById('max-storage').value);
        const maxFileSize = parseInt(document.getElementById('max-file-size').value);
        
        try {
            const response = await fetch('/api/update_config', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    'X-Admin-Token': localStorage.getItem('admin_token')
                },
                body: JSON.stringify({
                    max_storage: maxStorage,
                    max_file_size: maxFileSize
                })
            });
            
            const result = await response.json();
            if (result.status === 'success') {
                alert('配置更新成功');
                updateSystemStatus();
            } else {
                alert(`错误: ${result.message}`);
            }
        } catch (error) {
            console.error('配置更新失败:', error);
            alert('配置更新失败，请重试');
        }
    });
    
    // 登录表单提交
    document.getElementById('admin-login-btn').addEventListener('click', async () => {
        const username = document.getElementById('admin-username').value;
        const password = document.getElementById('admin-password').value;
        
        try {
            const response = await fetch('/admin/login', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({username, password})
            });
            
            if (response.ok) {
                const { token } = await response.json();
                localStorage.setItem('admin_token', token);
                document.getElementById('admin-login').style.display = 'none';
                document.querySelector('.admin-content').style.display = 'block';
            } else {
                alert('登录失败，请检查用户名和密码');
            }
        } catch (error) {
            console.error('登录失败:', error);
            alert('登录失败，请重试');
        }
    });
    
    // 检查现有会话
    if (localStorage.getItem('admin_token')) {
        document.getElementById('admin-login').style.display = 'none';
    } else {
        document.querySelector('.admin-content').style.display = 'none';
    }
});

// 检查登录状态并重定向
function checkAdminLogin() {
    if (!localStorage.getItem('admin_token')) {
        window.location.href = '/admin/login';
    }
}

// 初始化页面
document.addEventListener('DOMContentLoaded', () => {
    // 检查当前URL路径
    if (window.location.pathname === '/admin/login') {
        // 显示登录表单
        document.getElementById('admin-login').style.display = 'flex';
        document.querySelector('.admin-content').style.display = 'none';
        
        // 绑定登录按钮事件
        document.getElementById('admin-login-btn').addEventListener('click', async () => {
            const username = document.getElementById('admin-username').value;
            const password = document.getElementById('admin-password').value;
            
            try {
                const response = await fetch('/admin/login', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({username, password})
                });
                
                if (response.ok) {
                    const { token } = await response.json();
                    localStorage.setItem('admin_token', token);
                    window.location.href = '/admin'; // 登录成功后重定向
                } else {
                    alert('登录失败，请检查用户名和密码');
                }
            } catch (error) {
                console.error('登录失败:', error);
                alert('登录失败，请重试');
            }
        });
    } else if (window.location.pathname === '/admin') {
        // 检查管理员登录状态
        if (!localStorage.getItem('admin_token')) {
            window.location.href = '/admin/login';
            return;
        }
        
        // 初始化管理员仪表盘
        initAdminDashboard();
    }
});

// 初始化管理员仪表盘
function initAdminDashboard() {
    // 设置定时器定期更新状态
    setInterval(updateSystemStatus, 5000);
    
    // 初始更新
    updateSystemStatus();
    
    // 配置更新表单提交
    document.getElementById('storage-config-form').addEventListener('submit', async (e) => {
        e.preventDefault();
        
        const maxStorage = parseInt(document.getElementById('max-storage').value);
        const maxFileSize = parseInt(document.getElementById('max-file-size').value);
        
        try {
            const response = await fetch('/api/update_config', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    'X-Admin-Token': localStorage.getItem('admin_token')
                },
                body: JSON.stringify({
                    max_storage: maxStorage,
                    max_file_size: maxFileSize
                })
            });
            
            const result = await response.json();
            if (result.status === 'success') {
                alert('配置更新成功');
                updateSystemStatus();
            } else {
                alert(`错误: ${result.message}`);
            }
        } catch (error) {
            console.error('配置更新失败:', error);
            alert('配置更新失败，请重试');
        }
    });
}

// 更新系统状态显示
function updateSystemStatus() {
    fetch('/api/sysinfo')
        .then(response => response.json())
        .then(data => {
            // 更新磁盘使用情况
            document.getElementById('stat-files').textContent = data.file_count;
            document.getElementById('stat-downloads').textContent = data.total_downloads;
            
            const usagePercent = Math.round((data.disk.upload_used / data.disk.upload_total) * 100);
            document.getElementById('stat-usage').textContent = `${usagePercent}%`;
            
            // 更新运行时间
            const [days, time] = data.uptime.split(', ');
            const [hours, minutes, seconds] = time.split(':');
            document.getElementById('stat-uptime').textContent = 
                `${parseInt(days)}天 ${hours}小时 ${minutes}分 ${seconds}秒`;
            
            // 更新存储配置
            document.getElementById('max-storage').value = data.config.max_total_size;
            document.getElementById('max-file-size').value = data.config.max_file_size;
            
            // 更新存储使用情况
            document.getElementById('current-usage').textContent = formatBytes(data.disk.upload_used);
            document.getElementById('available-storage').textContent = formatBytes(data.disk.available);
            document.getElementById('usage-stat').textContent = formatBytes(data.disk.upload_used);
            document.getElementById('free-stat').textContent = formatBytes(data.disk.available);
            document.getElementById('total-stat').textContent = formatBytes(data.disk.upload_total);
            
            // 更新进度条
            document.getElementById('usage-bar').style.width = `${usagePercent}%`;
        })
        .catch(error => console.error('Error fetching system status:', error));
}