package main

import (
	"archive/zip"
	"bytes"
	"crypto/hmac"
	"crypto/md5"
	"crypto/rand"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"fmt"
	"io"
	"log"
	"math"
	"net"
	"net/http"
	"os"
	"os/exec"
	"path/filepath"
	"regexp"
	"runtime"
	"strconv"
	"strings"
	"sync"
	"time"

	"github.com/flosch/pongo2/v6"
	"github.com/shirou/gopsutil/v3/cpu"
	"github.com/shirou/gopsutil/v3/disk"
	"github.com/shirou/gopsutil/v3/mem"
	psnet "github.com/shirou/gopsutil/v3/net"
)

// ==============================================
// 常量定义
// ==============================================

const (
	ConfigFile   = "fileshare_config.json"
	MetadataFile = "files_metadata.json"
	LogDir       = "log"
	UploadDir    = "uploads"
)

// ==============================================
// 默认配置
// ==============================================

var DefaultConfig = map[string]interface{}{
	"upload_folder":            "uploads",
	"max_file_size":            float64(100),
	"max_total_size":           float64(1024),
	"app_name":                 "文件共享平台",
	"app_version":              "1.9",
	"admin_user":               "admin",
	"admin_password":           "admin@123",
	"port":                     float64(5000),
	"network_interface":        "auto",
	"geetest_id":               "",
	"geetest_key":              "",
	"offline_download_enabled": true,
}

// ==============================================
// 全局变量
// ==============================================

var (
	systemConfig      map[string]interface{}
	configMu          sync.RWMutex
	metadataMu        sync.Mutex
	downloadRecords   = make(map[string]time.Time)
	downloadRecordsMu sync.Mutex
	serviceStartTime  time.Time

	// GitHub克隆相关
	githubCloneQueue   = make(chan *GitHubCloner, 100)
	githubCloneTasks   = make(map[string]map[string]interface{})
	githubCloneTasksMu sync.Mutex
	activeCloners      = make(map[string]*GitHubCloner)
	activeClonersMu    sync.Mutex

	// 上传任务相关
	uploadTasks   = make(map[string]map[string]interface{})
	uploadTasksMu sync.Mutex

	// 离线下载相关
	offlineQueue       = make(chan string, 100)
	offlineTasks       = make(map[string]map[string]interface{})
	offlineTasksMu     sync.Mutex
	activeDownloaders  = make(map[string]*OfflineDownloader)
	activeDownloaderMu sync.Mutex

	// 管理员token (简单实现)
	adminTokens   = make(map[string]bool)
	adminTokensMu sync.Mutex
)

// ==============================================
// 日志系统
// ==============================================

var (
	systemLogger *log.Logger
	apiLogger    *log.Logger
	userLogger   *log.Logger
)

func initLogging() {
	os.MkdirAll(LogDir, 0755)

	dateStr := time.Now().Format("20060102")

	// 系统日志
	systemLogFile, err := os.OpenFile(filepath.Join(LogDir, "system_"+dateStr+".log"), os.O_CREATE|os.O_WRONLY|os.O_APPEND, 0644)
	if err == nil {
		systemLogger = log.New(io.MultiWriter(systemLogFile, os.Stdout), "", log.Ldate|log.Ltime)
	} else {
		systemLogger = log.New(os.Stdout, "", log.Ldate|log.Ltime)
	}

	// API日志
	apiLogFile, err := os.OpenFile(filepath.Join(LogDir, "api_"+dateStr+".log"), os.O_CREATE|os.O_WRONLY|os.O_APPEND, 0644)
	if err == nil {
		apiLogger = log.New(apiLogFile, "", log.Ldate|log.Ltime)
	} else {
		apiLogger = log.New(os.Stdout, "", log.Ldate|log.Ltime)
	}

	// 用户日志
	userLogFile, err := os.OpenFile(filepath.Join(LogDir, "user_"+dateStr+".log"), os.O_CREATE|os.O_WRONLY|os.O_APPEND, 0644)
	if err == nil {
		userLogger = log.New(userLogFile, "", log.Ldate|log.Ltime)
	} else {
		userLogger = log.New(os.Stdout, "", log.Ldate|log.Ltime)
	}
}

func logSystem(format string, v ...interface{}) {
	systemLogger.Printf(format, v...)
}

func logAPI(format string, v ...interface{}) {
	apiLogger.Printf(format, v...)
}

func logUser(format string, v ...interface{}) {
	userLogger.Printf(format, v...)
}

func getLogs(logType string, days int) string {
	var sb strings.Builder
	for i := 0; i < days; i++ {
		date := time.Now().AddDate(0, 0, -i).Format("20060102")
		logFile := filepath.Join(LogDir, logType+"_"+date+".log")
		if data, err := os.ReadFile(logFile); err == nil {
			sb.Write(data)
		}
	}
	if sb.Len() == 0 {
		return fmt.Sprintf("没有找到%s类型的日志记录\n", logType)
	}
	return sb.String()
}

// ==============================================
// 配置管理
// ==============================================

func getConfigString(key string) string {
	configMu.RLock()
	defer configMu.RUnlock()
	if v, ok := systemConfig[key]; ok {
		if s, ok := v.(string); ok {
			return s
		}
	}
	if v, ok := DefaultConfig[key]; ok {
		if s, ok := v.(string); ok {
			return s
		}
	}
	return ""
}

func getConfigFloat(key string) float64 {
	configMu.RLock()
	defer configMu.RUnlock()
	if v, ok := systemConfig[key]; ok {
		switch val := v.(type) {
		case float64:
			return val
		case int:
			return float64(val)
		}
	}
	if v, ok := DefaultConfig[key]; ok {
		if f, ok := v.(float64); ok {
			return f
		}
	}
	return 0
}

func getConfigBool(key string) bool {
	configMu.RLock()
	defer configMu.RUnlock()
	if v, ok := systemConfig[key]; ok {
		if b, ok := v.(bool); ok {
			return b
		}
	}
	if v, ok := DefaultConfig[key]; ok {
		if b, ok := v.(bool); ok {
			return b
		}
	}
	return false
}

func getConfigInt(key string) int {
	return int(getConfigFloat(key))
}

func setConfig(key string, value interface{}) {
	configMu.Lock()
	defer configMu.Unlock()
	systemConfig[key] = value
}

func getUploadFolder() string {
	folder := getConfigString("upload_folder")
	if !filepath.IsAbs(folder) {
		absPath, err := filepath.Abs(folder)
		if err == nil {
			return absPath
		}
	}
	return folder
}

func initSystem() {
	uploadFolder := getUploadFolder()
	os.MkdirAll(uploadFolder, 0755)

	// 加载配置
	if data, err := os.ReadFile(ConfigFile); err == nil {
		configMu.Lock()
		var savedConfig map[string]interface{}
		if json.Unmarshal(data, &savedConfig) == nil {
			for k, v := range savedConfig {
				if _, ok := systemConfig[k]; ok {
					systemConfig[k] = v
				}
			}
			// 检查缺失配置
			missing := false
			for k, v := range DefaultConfig {
				if _, ok := savedConfig[k]; !ok {
					systemConfig[k] = v
					missing = true
				}
			}
			if missing {
				saveConfig()
			}
		}
		configMu.Unlock()
	}

	// 确保元数据文件有效
	if _, err := os.Stat(MetadataFile); os.IsNotExist(err) {
		os.WriteFile(MetadataFile, []byte("{}"), 0644)
	} else if info, err := os.Stat(MetadataFile); err == nil && info.Size() == 0 {
		os.WriteFile(MetadataFile, []byte("{}"), 0644)
	}

	logSystem("系统初始化完成,元数据文件已就绪")
}

func saveConfig() {
	configMu.RLock()
	data, err := json.MarshalIndent(systemConfig, "", "    ")
	configMu.RUnlock()
	if err != nil {
		logSystem("配置保存失败: %v", err)
		return
	}
	if err := os.WriteFile(ConfigFile, data, 0644); err != nil {
		logSystem("配置保存失败: %v", err)
	} else {
		logSystem("配置保存成功")
	}
}

func loadConfig() {
	configMu.Lock()
	defer configMu.Unlock()

	if data, err := os.ReadFile(ConfigFile); err == nil {
		var savedConfig map[string]interface{}
		if json.Unmarshal(data, &savedConfig) == nil {
			tempConfig := make(map[string]interface{})
			for k, v := range DefaultConfig {
				tempConfig[k] = v
			}
			missing := false
			for k, v := range savedConfig {
				if _, ok := tempConfig[k]; ok {
					tempConfig[k] = v
				}
			}
			for k, v := range DefaultConfig {
				if _, ok := savedConfig[k]; !ok {
					tempConfig[k] = v
					missing = true
				}
			}
			systemConfig = tempConfig
			if missing {
				saveConfig()
			}
			logSystem("配置文件加载成功")
			return
		}
	}
	// 使用默认配置
	systemConfig = make(map[string]interface{})
	for k, v := range DefaultConfig {
		systemConfig[k] = v
	}
	saveConfig()
	logSystem("配置文件不存在，使用默认配置")
}

// ==============================================
// 文件元数据管理
// ==============================================

func loadMetadata() map[string]map[string]interface{} {
	metadataMu.Lock()
	defer metadataMu.Unlock()

	if _, err := os.Stat(MetadataFile); os.IsNotExist(err) {
		os.WriteFile(MetadataFile, []byte("{}"), 0644)
		return make(map[string]map[string]interface{})
	}

	data, err := os.ReadFile(MetadataFile)
	if err != nil {
		os.WriteFile(MetadataFile, []byte("{}"), 0644)
		return make(map[string]map[string]interface{})
	}

	if len(data) == 0 {
		os.WriteFile(MetadataFile, []byte("{}"), 0644)
		return make(map[string]map[string]interface{})
	}

	var metadata map[string]map[string]interface{}
	if err := json.Unmarshal(data, &metadata); err != nil {
		os.WriteFile(MetadataFile, []byte("{}"), 0644)
		return make(map[string]map[string]interface{})
	}

	return metadata
}

func saveMetadata(metadata map[string]map[string]interface{}) {
	data, err := json.MarshalIndent(metadata, "", "    ")
	if err != nil {
		logSystem("元数据保存失败: %v", err)
		return
	}
	if err := os.WriteFile(MetadataFile, data, 0644); err != nil {
		logSystem("元数据保存失败: %v", err)
	}
}

func updateMetadata(filename, action string) map[string]interface{} {
	metadata := loadMetadata()
	filePath := filepath.Join(getUploadFolder(), filename)

	if action != "delete" {
		if _, err := os.Stat(filePath); os.IsNotExist(err) {
			return nil
		}
	}

	if action != "delete" {
		info, _ := os.Stat(filePath)
		fileSize := info.Size()
		fileMtime := float64(info.ModTime().Unix())
		fileCtime := fileMtime

		if _, ok := metadata[filename]; !ok {
			metadata[filename] = map[string]interface{}{
				"size":           float64(fileSize),
				"created":        fileCtime,
				"modified":       fileMtime,
				"download_count": float64(0),
			}
		}

		if action == "download" {
			downloadRecordsMu.Lock()
			lastTime, exists := downloadRecords[filename]
			now := time.Now()
			if !exists || now.Sub(lastTime) > time.Second {
				if count, ok := metadata[filename]["download_count"].(float64); ok {
					metadata[filename]["download_count"] = count + 1
				}
				downloadRecords[filename] = now
			}
			downloadRecordsMu.Unlock()
		} else if action == "upload" {
			metadata[filename]["size"] = float64(fileSize)
			metadata[filename]["modified"] = fileMtime
		}
	} else {
		delete(metadata, filename)
		downloadRecordsMu.Lock()
		delete(downloadRecords, filename)
		downloadRecordsMu.Unlock()
	}

	saveMetadata(metadata)

	if action != "delete" {
		return metadata[filename]
	}
	return nil
}

func getFileList() []map[string]interface{} {
	uploadDir := getUploadFolder()
	if _, err := os.Stat(uploadDir); os.IsNotExist(err) {
		return nil
	}

	metadata := loadMetadata()
	entries, err := os.ReadDir(uploadDir)
	if err != nil {
		return nil
	}

	var files []map[string]interface{}
	for _, entry := range entries {
		if entry.IsDir() {
			continue
		}
		filename := entry.Name()
		if strings.Contains(filename, "../") {
			continue
		}

		filePath := filepath.Join(uploadDir, filename)
		info, err := os.Stat(filePath)
		if err != nil {
			continue
		}

		ext := filepath.Ext(filename)
		nameWithoutExt := strings.TrimSuffix(filename, ext)
		extClean := strings.TrimPrefix(ext, ".")

		fileMeta := metadata[filename]
		downloadCount := float64(0)
		if fileMeta != nil {
			if count, ok := fileMeta["download_count"].(float64); ok {
				downloadCount = count
			}
		}

		files = append(files, map[string]interface{}{
			"filename":         filename,
			"name":             filename,
			"name_without_ext": nameWithoutExt,
			"extension":        strings.ToLower(extClean),
			"size":             float64(info.Size()),
			"filesize":         float64(info.Size()),
			"modified":         float64(info.ModTime().Unix()),
			"created":          float64(time.Now().Unix()),
			"download_count":   downloadCount,
		})
	}

	// 按修改时间排序
	for i := 0; i < len(files); i++ {
		for j := i + 1; j < len(files); j++ {
			mi, _ := files[i]["modified"].(float64)
			mj, _ := files[j]["modified"].(float64)
			if mj > mi {
				files[i], files[j] = files[j], files[i]
			}
		}
	}

	return files
}

// ==============================================
// 系统资源
// ==============================================

func getDiskUsage() map[string]interface{} {
	uploadDir := getUploadFolder()
	os.MkdirAll(uploadDir, 0755)

	// 计算上传目录使用空间
	var uploadUsage int64
	filepath.Walk(uploadDir, func(path string, info os.FileInfo, err error) error {
		if err != nil {
			return nil
		}
		if !info.IsDir() {
			uploadUsage += info.Size()
		}
		return nil
	})

	maxTotalBytes := int64(getConfigFloat("max_total_size")) * 1024 * 1024

	// 获取系统磁盘信息
	var systemTotal, systemUsed, systemFree uint64
	usage, err := disk.Usage(uploadDir)
	if err == nil {
		systemTotal = usage.Total
		systemUsed = usage.Used
		systemFree = usage.Free
	}

	available := int64(systemFree)
	configAvail := maxTotalBytes - uploadUsage
	if configAvail < available {
		available = configAvail
	}
	if available < 0 {
		available = 0
	}

	usagePercent := 0
	if maxTotalBytes > 0 {
		usagePercent = int(math.Min(100, float64(uploadUsage)/float64(maxTotalBytes)*100))
	}

	return map[string]interface{}{
		"system_total":  float64(systemTotal),
		"system_used":   float64(systemUsed),
		"system_free":   float64(systemFree),
		"upload_total":  float64(maxTotalBytes),
		"upload_used":   float64(uploadUsage),
		"available":     float64(available),
		"usage_percent": float64(usagePercent),
	}
}

func getSystemResources() map[string]interface{} {
	cpuPercent, err := cpu.Percent(time.Second, false)
	cpuVal := 0.0
	if err == nil && len(cpuPercent) > 0 {
		cpuVal = cpuPercent[0]
	}

	memInfo, err := mem.VirtualMemory()
	memPercent := 0.0
	memTotal := uint64(0)
	memUsed := uint64(0)
	if err == nil {
		memPercent = memInfo.UsedPercent
		memTotal = memInfo.Total
		memUsed = memInfo.Used
	}

	var interfaces []map[string]interface{}
	ifaces, err := psnet.Interfaces()
	if err == nil {
		for _, iface := range ifaces {
			for _, addr := range iface.Addrs {
				if addr.Addr != "" {
					interfaces = append(interfaces, map[string]interface{}{
						"interface": iface.Name,
						"ip":        addr.Addr,
					})
				}
			}
		}
	}

	return map[string]interface{}{
		"cpu_percent": cpuVal,
		"mem_percent": memPercent,
		"mem_total":   float64(memTotal),
		"mem_used":    float64(memUsed),
		"interfaces":  interfaces,
	}
}

// ==============================================
// 工具函数
// ==============================================

func convertSize(sizeBytes float64) string {
	size := int64(sizeBytes)
	if size == 0 {
		return "0B"
	}
	units := []string{"B", "KB", "MB", "GB", "TB"}
	i := 0
	fSize := float64(size)
	for fSize >= 1024 && i < len(units)-1 {
		fSize /= 1024.0
		i++
	}
	if fSize < 10 {
		return fmt.Sprintf("%.2f %s", fSize, units[i])
	} else if fSize < 100 {
		return fmt.Sprintf("%.1f %s", fSize, units[i])
	}
	return fmt.Sprintf("%.0f %s", fSize, units[i])
}

func secureFilename(filename string) string {
	filename = strings.ReplaceAll(filename, "/", "_")
	filename = strings.ReplaceAll(filename, "\\", "_")
	filename = strings.ReplaceAll(filename, "<", "")
	filename = strings.ReplaceAll(filename, ">", "")
	filename = strings.ReplaceAll(filename, ":", "")
	filename = strings.ReplaceAll(filename, "\"", "")
	filename = strings.ReplaceAll(filename, "|", "")
	filename = strings.ReplaceAll(filename, "?", "")
	filename = strings.ReplaceAll(filename, "*", "")
	return filename
}

func getRealIP(r *http.Request) string {
	if realIP := r.Header.Get("X-Real-IP"); realIP != "" {
		return realIP
	}
	if xff := r.Header.Get("X-Forwarded-For"); xff != "" {
		parts := strings.Split(xff, ",")
		return strings.TrimSpace(parts[0])
	}
	host, _, err := net.SplitHostPort(r.RemoteAddr)
	if err != nil {
		return r.RemoteAddr
	}
	return host
}

func generateToken() string {
	b := make([]byte, 24)
	rand.Read(b)
	return hex.EncodeToString(b)
}

func jsonResponse(w http.ResponseWriter, status int, data interface{}) {
	w.Header().Set("Content-Type", "application/json; charset=utf-8")
	w.WriteHeader(status)
	json.NewEncoder(w).Encode(data)
}

func jsonError(w http.ResponseWriter, status int, message string) {
	jsonResponse(w, status, map[string]interface{}{
		"status":  "error",
		"message": message,
	})
}

func jsonSuccess(w http.ResponseWriter, data map[string]interface{}) {
	if data == nil {
		data = make(map[string]interface{})
	}
	data["status"] = "success"
	jsonResponse(w, 200, data)
}

// ==============================================
// 认证中间件
// ==============================================

func requireAdminToken(next http.HandlerFunc) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		// Cookie中的token
		cookie, _ := r.Cookie("admin_token")
		cookieToken := ""
		if cookie != nil {
			cookieToken = cookie.Value
		}

		// Header中的token
		headerToken := r.Header.Get("X-Admin-Token")

		// 验证逻辑
		if cookieToken != "" && headerToken != "" && cookieToken == headerToken {
			next(w, r)
			return
		}
		if cookieToken != "" && headerToken == "" {
			adminTokensMu.Lock()
			valid := adminTokens[cookieToken]
			adminTokensMu.Unlock()
			if valid {
				next(w, r)
				return
			}
		}
		if headerToken != "" && cookieToken == "" {
			// 兼容localStorage方式
			next(w, r)
			return
		}

		jsonError(w, 403, "未授权访问，请重新登录")
	}
}

// ==============================================
// Git操作
// ==============================================

func isGitInstalled() bool {
	cmd := exec.Command("git", "--version")
	err := cmd.Run()
	return err == nil
}

func installGit() bool {
	if runtime.GOOS != "windows" {
		return false
	}
	cmd := exec.Command("winget", "install", "--id", "Git.Git", "-e", "--source", "winget")
	cmd.Run()
	return isGitInstalled()
}

// ==============================================
// GitHub克隆器
// ==============================================

type GitHubCloner struct {
	RepoURL   string
	TaskID    string
	Branch    string
	TempDir   string
	ZipPath   string
	FileName  string
	Status    string
	Progress  int
	StartTime time.Time
	Error     string
	CloneDir  string
	Process   *exec.Cmd
	Cancelled bool
	mu        sync.Mutex
}

func NewGitHubCloner(repoURL, taskID, branch string) *GitHubCloner {
	return &GitHubCloner{
		RepoURL:   repoURL,
		TaskID:    taskID,
		Branch:    branch,
		Status:    "pending",
		StartTime: time.Now(),
	}
}

func (g *GitHubCloner) GetRepoName() string {
	// 从URL中提取仓库名
	repoURL := g.RepoURL
	repoURL = strings.TrimSuffix(repoURL, ".git")
	repoURL = strings.TrimSuffix(repoURL, "/")
	parts := strings.Split(repoURL, "/")
	if len(parts) >= 2 {
		return parts[len(parts)-2] + "_" + parts[len(parts)-1]
	}
	return fmt.Sprintf("repo_%s", g.TaskID)
}

func (g *GitHubCloner) Cancel() {
	g.mu.Lock()
	defer g.mu.Unlock()
	g.Cancelled = true
	g.Status = "cancelled"
	if g.Process != nil && g.Process.Process != nil {
		g.Process.Process.Kill()
	}
}

func (g *GitHubCloner) Run() {
	g.mu.Lock()
	g.Status = "cloning"
	g.mu.Unlock()

	var err error
	g.TempDir, err = os.MkdirTemp("", "github_clone_")
	if err != nil {
		g.mu.Lock()
		g.Error = err.Error()
		g.Status = "failed"
		g.mu.Unlock()
		return
	}
	defer os.RemoveAll(g.TempDir)

	g.FileName = fmt.Sprintf("%s_%s_%d.zip", g.GetRepoName(), g.Branch, time.Now().Unix())
	g.CloneDir = filepath.Join(g.TempDir, g.GetRepoName())

	// 检查Git安装
	if !isGitInstalled() {
		g.mu.Lock()
		g.Status = "installing_git"
		g.mu.Unlock()
		if !installGit() {
			g.mu.Lock()
			g.Error = "Git安装失败,请手动安装Git"
			g.Status = "failed"
			g.mu.Unlock()
			return
		}
	}

	// 克隆仓库
	cloneCmd := exec.Command("git", "clone", "--depth", "1", "-b", g.Branch, g.RepoURL, g.CloneDir)
	g.mu.Lock()
	g.Process = cloneCmd
	g.Progress = 10
	g.mu.Unlock()

	output, err := cloneCmd.CombinedOutput()

	g.mu.Lock()
	if g.Cancelled {
		g.mu.Unlock()
		return
	}
	g.mu.Unlock()

	if err != nil {
		lines := strings.Split(string(output), "\n")
		lastLines := ""
		start := len(lines) - 5
		if start < 0 {
			start = 0
		}
		lastLines = strings.Join(lines[start:], "\n")
		g.mu.Lock()
		g.Error = lastLines
		g.Status = "failed"
		g.mu.Unlock()
		return
	}

	// 创建ZIP
	g.mu.Lock()
	g.Status = "compressing"
	g.Progress = 85
	g.mu.Unlock()

	g.ZipPath = filepath.Join(g.TempDir, g.FileName)
	zipFile, err := os.Create(g.ZipPath)
	if err != nil {
		g.mu.Lock()
		g.Error = err.Error()
		g.Status = "failed"
		g.mu.Unlock()
		return
	}
	defer zipFile.Close()

	zipWriter := zip.NewWriter(zipFile)
	defer zipWriter.Close()

	filepath.Walk(g.CloneDir, func(path string, info os.FileInfo, err error) error {
		if err != nil || info.IsDir() {
			return nil
		}
		relPath, _ := filepath.Rel(g.TempDir, path)
		writer, err := zipWriter.Create(relPath)
		if err != nil {
			return nil
		}
		file, err := os.Open(path)
		if err != nil {
			return nil
		}
		defer file.Close()
		io.Copy(writer, file)
		return nil
	})

	g.mu.Lock()
	g.Progress = 100
	g.Status = "completed"
	g.mu.Unlock()
}

// GitHub克隆工作线程
func startGitHubCloneWorker() {
	go func() {
		for cloner := range githubCloneQueue {
			activeClonersMu.Lock()
			activeCloners[cloner.TaskID] = cloner
			activeClonersMu.Unlock()

			cloner.Run()

			githubCloneTasksMu.Lock()
			githubCloneTasks[cloner.TaskID] = map[string]interface{}{
				"status":     cloner.Status,
				"progress":   cloner.Progress,
				"repo_url":   cloner.RepoURL,
				"file_name":  cloner.FileName,
				"error":      cloner.Error,
				"start_time": cloner.StartTime.Unix(),
				"branch":     cloner.Branch,
			}
			githubCloneTasksMu.Unlock()

			activeClonersMu.Lock()
			delete(activeCloners, cloner.TaskID)
			activeClonersMu.Unlock()
		}
	}()
}

// ==============================================
// 离线下载器
// ==============================================

type OfflineDownloader struct {
	TaskID    string
	URL       string
	Filename  string
	Status    string
	Progress  int
	Error     string
	TempFile  string
	Cancelled bool
	StartTime time.Time
	mu        sync.Mutex
}

func NewOfflineDownloader(taskID, url, filename string) *OfflineDownloader {
	return &OfflineDownloader{
		TaskID:    taskID,
		URL:       url,
		Filename:  filename,
		Status:    "downloading",
		StartTime: time.Now(),
	}
}

func (d *OfflineDownloader) Cancel() {
	d.mu.Lock()
	defer d.mu.Unlock()
	d.Cancelled = true
	d.Status = "cancelled"
}

func (d *OfflineDownloader) Run() {
	offlineTasksMu.Lock()
	if task, ok := offlineTasks[d.TaskID]; ok {
		task["status"] = "downloading"
	}
	offlineTasksMu.Unlock()

	// 创建临时目录
	tempDir, err := os.MkdirTemp("", "offline_download_")
	if err != nil {
		d.mu.Lock()
		d.Error = err.Error()
		d.Status = "failed"
		d.mu.Unlock()
		return
	}
	defer os.RemoveAll(tempDir)

	d.TempFile = filepath.Join(tempDir, d.Filename)

	// 下载文件
	resp, err := http.Get(d.URL)
	if err != nil {
		d.mu.Lock()
		d.Error = err.Error()
		d.Status = "failed"
		d.mu.Unlock()
		offlineTasksMu.Lock()
		if task, ok := offlineTasks[d.TaskID]; ok {
			task["status"] = "failed"
			task["error"] = err.Error()
		}
		offlineTasksMu.Unlock()
		return
	}
	defer resp.Body.Close()

	totalSize := resp.ContentLength
	var downloaded int64

	file, err := os.Create(d.TempFile)
	if err != nil {
		d.mu.Lock()
		d.Error = err.Error()
		d.Status = "failed"
		d.mu.Unlock()
		return
	}
	defer file.Close()

	buf := make([]byte, 8192)
	for {
		d.mu.Lock()
		if d.Cancelled {
			d.mu.Unlock()
			return
		}
		d.mu.Unlock()

		n, readErr := resp.Body.Read(buf)
		if n > 0 {
			file.Write(buf[:n])
			downloaded += int64(n)

			if totalSize > 0 {
				d.mu.Lock()
				d.Progress = int(float64(downloaded) / float64(totalSize) * 100)
				d.mu.Unlock()
			}

			offlineTasksMu.Lock()
			if task, ok := offlineTasks[d.TaskID]; ok {
				task["progress"] = d.Progress
			}
			offlineTasksMu.Unlock()
		}
		if readErr != nil {
			break
		}
	}

	// 检查是否取消
	d.mu.Lock()
	if d.Cancelled {
		d.mu.Unlock()
		return
	}
	d.mu.Unlock()

	// 移动到上传目录
	fileInfo, err := os.Stat(d.TempFile)
	if err != nil || fileInfo.Size() == 0 {
		d.mu.Lock()
		d.Error = "文件下载失败，文件为空或不存在"
		d.Status = "failed"
		d.mu.Unlock()
		offlineTasksMu.Lock()
		if task, ok := offlineTasks[d.TaskID]; ok {
			task["status"] = "failed"
			task["error"] = d.Error
		}
		offlineTasksMu.Unlock()
		return
	}

	uploadPath := filepath.Join(getUploadFolder(), d.Filename)
	counter := 1
	ext := filepath.Ext(d.Filename)
	name := strings.TrimSuffix(d.Filename, ext)
	for {
		if _, err := os.Stat(uploadPath); os.IsNotExist(err) {
			break
		}
		uploadPath = filepath.Join(getUploadFolder(), fmt.Sprintf("%s_%d%s", name, counter, ext))
		counter++
	}

	os.Rename(d.TempFile, uploadPath)
	updateMetadata(filepath.Base(uploadPath), "upload")

	offlineTasksMu.Lock()
	if task, ok := offlineTasks[d.TaskID]; ok {
		task["status"] = "completed"
		task["progress"] = 100
		task["filename"] = filepath.Base(uploadPath)
	}
	offlineTasksMu.Unlock()
}

// 离线下载工作线程
func startOfflineDownloadWorker() {
	go func() {
		for taskID := range offlineQueue {
			offlineTasksMu.Lock()
			task, ok := offlineTasks[taskID]
			offlineTasksMu.Unlock()

			if !ok {
				continue
			}

			url, _ := task["url"].(string)
			filename, _ := task["filename"].(string)

			downloader := NewOfflineDownloader(taskID, url, filename)

			activeDownloaderMu.Lock()
			activeDownloaders[taskID] = downloader
			activeDownloaderMu.Unlock()

			downloader.Run()

			activeDownloaderMu.Lock()
			delete(activeDownloaders, taskID)
			activeDownloaderMu.Unlock()
		}
	}()
}

// ==============================================
// 模板渲染辅助函数
// ==============================================

func renderTemplate(w http.ResponseWriter, templateName string, ctx pongo2.Context) {
	tpl, err := pongo2.FromCache("templates/" + templateName)
	if err != nil {
		http.Error(w, "Template error: "+err.Error(), 500)
		return
	}
	output, err := tpl.Execute(ctx)
	if err != nil {
		http.Error(w, "Template render error: "+err.Error(), 500)
		return
	}
	w.Header().Set("Content-Type", "text/html; charset=utf-8")
	w.Write([]byte(output))
}

// ==============================================
// HTTP 处理器
// ==============================================

// 首页
func handleIndex(w http.ResponseWriter, r *http.Request) {
	disk := getDiskUsage()
	files := getFileList()

	uploadTotal, _ := disk["upload_total"].(float64)
	uploadUsed, _ := disk["upload_used"].(float64)
	available, _ := disk["available"].(float64)
	usagePercent, _ := disk["usage_percent"].(float64)

	renderTemplate(w, "index.html", pongo2.Context{
		"files":         files,
		"app_name":      getConfigString("app_name"),
		"total_space":   convertSize(uploadTotal),
		"used_space":    convertSize(uploadUsed),
		"free_space":    convertSize(available),
		"max_file_size": getConfigFloat("max_file_size"),
		"usage_percent": usagePercent,
	})
}

// 下载页面
func handleDownloadPage(w http.ResponseWriter, r *http.Request) {
	renderTemplate(w, "download_page.html", nil)
}

// 管理员页面
func handleAdmin(w http.ResponseWriter, r *http.Request) {
	cookie, err := r.Cookie("admin_token")
	if err != nil || cookie == nil {
		http.Redirect(w, r, "/admin/login", 302)
		return
	}
	adminTokensMu.Lock()
	valid := adminTokens[cookie.Value]
	adminTokensMu.Unlock()
	if !valid {
		http.Redirect(w, r, "/admin/login", 302)
		return
	}

	diskInfo := getDiskUsage()
	sysResources := getSystemResources()
	files := getFileList()

	diskSpace := map[string]interface{}{
		"percent": diskInfo["usage_percent"],
		"used":    diskInfo["upload_used"],
		"free":    diskInfo["available"],
		"total":   diskInfo["upload_total"],
	}

	uploadTotal, _ := diskInfo["upload_total"].(float64)
	uploadUsed, _ := diskInfo["upload_used"].(float64)
	systemTotal, _ := diskInfo["system_total"].(float64)
	systemUsed, _ := diskInfo["system_used"].(float64)
	memTotal, _ := sysResources["mem_total"].(float64)
	memUsed, _ := sysResources["mem_used"].(float64)

	uptime := time.Since(serviceStartTime).String()

	renderTemplate(w, "admin.html", pongo2.Context{
		"disk_space":        diskSpace,
		"files":             files,
		"system_config":     systemConfig,
		"share_folder":      getUploadFolder(),
		"max_file_size":     getConfigFloat("max_file_size"),
		"max_total_size":    getConfigFloat("max_total_size"),
		"system_total":      convertSize(systemTotal),
		"system_used":       convertSize(systemUsed),
		"upload_used":       convertSize(uploadUsed),
		"upload_total":      convertSize(uploadTotal),
		"service_start":     serviceStartTime.Format("2006-01-02 15:04:05"),
		"uptime":            uptime,
		"cpu_percent":       sysResources["cpu_percent"],
		"mem_percent":       sysResources["mem_percent"],
		"mem_total":         convertSize(memTotal),
		"mem_used":          convertSize(memUsed),
		"interfaces":        sysResources["interfaces"],
		"port":              getConfigInt("port"),
		"network_interface": getConfigString("network_interface"),
		"geetest_id":        getConfigString("geetest_id"),
		"geetest_key":       getConfigString("geetest_key"),
	})
}

// 管理员登录页面
func handleAdminLoginGet(w http.ResponseWriter, r *http.Request) {
	renderTemplate(w, "admin_login.html", nil)
}

// 管理员登录API
func handleAdminLoginPost(w http.ResponseWriter, r *http.Request) {
	var data map[string]string
	if err := json.NewDecoder(r.Body).Decode(&data); err != nil {
		jsonError(w, 400, "无效请求")
		return
	}

	username := data["username"]
	password := data["password"]

	if username == getConfigString("admin_user") && password == getConfigString("admin_password") {
		token := generateToken()
		adminTokensMu.Lock()
		adminTokens[token] = true
		adminTokensMu.Unlock()

		// 设置Cookie
		http.SetCookie(w, &http.Cookie{
			Name:     "admin_token",
			Value:    token,
			Path:     "/",
			HttpOnly: true,
			MaxAge:   86400,
		})

		jsonSuccess(w, map[string]interface{}{
			"token": token,
		})
		return
	}

	jsonError(w, 401, "无效凭据")
}

// 管理员登出
func handleAdminLogout(w http.ResponseWriter, r *http.Request) {
	cookie, _ := r.Cookie("admin_token")
	if cookie != nil {
		adminTokensMu.Lock()
		delete(adminTokens, cookie.Value)
		adminTokensMu.Unlock()
	}
	http.SetCookie(w, &http.Cookie{
		Name:   "admin_token",
		Value:  "",
		Path:   "/",
		MaxAge: -1,
	})
	http.Redirect(w, r, "/admin/login", 302)
}

// 修改密码
func handleAdminChangePassword(w http.ResponseWriter, r *http.Request) {
	currentPassword := r.FormValue("current_password")
	newPassword := r.FormValue("new_password")
	confirmPassword := r.FormValue("confirm_password")

	if currentPassword != getConfigString("admin_password") {
		http.Redirect(w, r, "/admin", 302)
		return
	}
	if newPassword != confirmPassword {
		http.Redirect(w, r, "/admin", 302)
		return
	}

	setConfig("admin_password", newPassword)
	saveConfig()
	http.Redirect(w, r, "/admin", 302)
}

// GitHub克隆管理页面
func handleAdminGitHubClone(w http.ResponseWriter, r *http.Request) {
	disk := getDiskUsage()
	files := getFileList()

	renderTemplate(w, "github_clone.html", pongo2.Context{
		"files":          files,
		"disk":           disk,
		"max_file_size":  getConfigFloat("max_file_size"),
		"max_total_size": getConfigFloat("max_total_size"),
		"upload_folder":  getUploadFolder(),
	})
}

// 文件列表API
func handleAPIFiles(w http.ResponseWriter, r *http.Request) {
	files := getFileList()
	disk := getDiskUsage()

	var formattedFiles []map[string]interface{}
	for _, file := range files {
		filename, _ := file["filename"].(string)
		name, _ := file["name"].(string)
		formattedFiles = append(formattedFiles, map[string]interface{}{
			"filename":       filename,
			"name":           name,
			"size":           file["size"],
			"modified":       file["modified"],
			"download_count": file["download_count"],
			"hash":           name,
		})
	}

	uploadUsed, _ := disk["upload_used"].(float64)
	maxStorage := getConfigFloat("max_total_size") * 1024 * 1024

	jsonSuccess(w, map[string]interface{}{
		"files":       formattedFiles,
		"disk_used":   uploadUsed,
		"max_storage": maxStorage,
	})
}

// 文件上传API
func handleUpload(w http.ResponseWriter, r *http.Request) {
	file, header, err := r.FormFile("file")
	if err != nil {
		jsonError(w, 400, "未选择文件")
		return
	}
	defer file.Close()

	filename := header.Filename
	if filename == "" || !strings.Contains(filename, ".") {
		jsonError(w, 400, "无效的文件名")
		return
	}

	// 获取文件大小
	fileSize := header.Size

	// 检查大小限制
	maxSize := int64(getConfigFloat("max_file_size")) * 1024 * 1024
	if fileSize > maxSize {
		jsonError(w, 400, fmt.Sprintf("文件大小超过限制 (%s)", convertSize(float64(maxSize))))
		return
	}

	// 检查空间
	disk := getDiskUsage()
	available, _ := disk["available"].(float64)
	if fileSize > int64(available) {
		jsonError(w, 400, fmt.Sprintf("磁盘空间不足(可用空间：%s)", convertSize(available)))
		return
	}

	// 安全文件名
	filename = secureFilename(filename)
	savePath := filepath.Join(getUploadFolder(), filename)

	// 处理重名
	counter := 1
	ext := filepath.Ext(filename)
	name := strings.TrimSuffix(filename, ext)
	for {
		if _, err := os.Stat(savePath); os.IsNotExist(err) {
			break
		}
		filename = fmt.Sprintf("%s_%d%s", name, counter, ext)
		savePath = filepath.Join(getUploadFolder(), filename)
		counter++
	}

	// 保存文件
	dst, err := os.Create(savePath)
	if err != nil {
		jsonError(w, 500, fmt.Sprintf("保存失败: %s", err.Error()))
		return
	}
	defer dst.Close()

	if _, err := io.Copy(dst, file); err != nil {
		jsonError(w, 500, fmt.Sprintf("保存失败: %s", err.Error()))
		return
	}

	updateMetadata(filename, "upload")
	jsonSuccess(w, map[string]interface{}{
		"filename": filename,
	})
}

// 删除文件API
func handleAPIDeleteFile(w http.ResponseWriter, r *http.Request) {
	var data map[string]string
	if err := json.NewDecoder(r.Body).Decode(&data); err != nil {
		jsonError(w, 400, "文件名不能为空")
		return
	}

	filename := data["filename"]
	if filename == "" {
		jsonError(w, 400, "文件名不能为空")
		return
	}

	// 安全检查
	if strings.Contains(filename, "../") || !regexp.MustCompile(`^[\w\-. ]+$`).MatchString(filename) {
		jsonError(w, 400, "无效的文件名")
		return
	}

	filePath := filepath.Join(getUploadFolder(), filename)
	realUploadDir, _ := filepath.Abs(getUploadFolder())
	realFilePath, _ := filepath.Abs(filePath)

	if !strings.HasPrefix(realFilePath, realUploadDir) {
		jsonError(w, 400, "文件不在上传目录内")
		return
	}

	if _, err := os.Stat(filePath); os.IsNotExist(err) {
		jsonError(w, 404, "文件不存在")
		return
	}

	if err := os.Remove(filePath); err != nil {
		jsonError(w, 500, fmt.Sprintf("删除失败: %s", err.Error()))
		return
	}

	updateMetadata(filename, "delete")
	jsonSuccess(w, map[string]interface{}{
		"message": "文件已删除",
	})
}

// 多文件上传页面
func handleMultiUploadPage(w http.ResponseWriter, r *http.Request) {
	renderTemplate(w, "multi_upload.html", pongo2.Context{
		"app_name":       getConfigString("app_name"),
		"max_file_size":  getConfigFloat("max_file_size"),
		"max_total_size": getConfigFloat("max_total_size"),
		"upload_folder":  getUploadFolder(),
	})
}

// 多文件上传API
func handleMultiUpload(w http.ResponseWriter, r *http.Request) {
	// 与单文件上传逻辑相同
	handleUpload(w, r)
}

// 文件下载
func handleDownload(w http.ResponseWriter, r *http.Request) {
	filename := r.PathValue("filename")
	if strings.Contains(filename, "../") {
		http.Error(w, "Bad Request", 400)
		return
	}

	uploadDir := getUploadFolder()
	filePath := filepath.Join(uploadDir, filename)

	if info, err := os.Stat(filePath); err != nil || info.IsDir() {
		http.Error(w, "Not Found", 404)
		return
	}

	updateMetadata(filename, "download")

	w.Header().Set("Content-Disposition", fmt.Sprintf(`attachment; filename="%s"`, filename))
	http.ServeFile(w, r, filePath)
}

// 文件预览
func handlePreview(w http.ResponseWriter, r *http.Request) {
	filename := r.PathValue("filename")
	if strings.Contains(filename, "../") {
		http.Error(w, "Bad Request", 400)
		return
	}

	uploadDir := getUploadFolder()
	filePath := filepath.Join(uploadDir, filename)

	if info, err := os.Stat(filePath); err != nil || info.IsDir() {
		http.Error(w, "Not Found", 404)
		return
	}

	ext := strings.ToLower(filepath.Ext(filename))
	mimeTypes := map[string]string{
		".mp4":  "video/mp4",
		".webm": "video/webm",
		".ogg":  "video/ogg",
		".avi":  "video/x-msvideo",
		".mov":  "video/quicktime",
		".wmv":  "video/x-ms-wmv",
		".flv":  "video/x-flv",
		".mkv":  "video/x-matroska",
		".m4v":  "video/x-m4v",
		".3gp":  "video/3gpp",
		".3g2":  "video/3gpp2",
		".mpg":  "video/mpeg",
		".mpeg": "video/mpeg",
		".ts":   "video/mp2t",
		".m2ts": "video/mp2t",
		".mp3":  "audio/mpeg",
		".wav":  "audio/wav",
		".aac":  "audio/aac",
		".jpg":  "image/jpeg",
		".jpeg": "image/jpeg",
		".png":  "image/png",
		".gif":  "image/gif",
		".webp": "image/webp",
		".pdf":  "application/pdf",
		".txt":  "text/plain; charset=utf-8",
		".zip":  "application/zip",
		".rar":  "application/x-rar-compressed",
		".7z":   "application/x-7z-compressed",
		".exe":  "application/x-msdownload",
		".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
		".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
		".pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
		".doc":  "application/msword",
		".xls":  "application/vnd.ms-excel",
		".ppt":  "application/vnd.ms-powerpoint",
	}

	mimeType, ok := mimeTypes[ext]
	if !ok {
		mimeType = "application/octet-stream"
	}

	fileSize, _ := os.Stat(filePath)

	// 支持Range请求的视频/音频
	mediaExts := []string{".mp4", ".webm", ".ogg", ".avi", ".mov", ".wmv", ".flv", ".mkv", ".m4v", ".3gp", ".3g2", ".mpg", ".mpeg", ".ts", ".m2ts", ".mp3", ".wav", ".aac"}
	isMedia := false
	for _, me := range mediaExts {
		if ext == me {
			isMedia = true
			break
		}
	}

	if isMedia {
		rangeHeader := r.Header.Get("Range")
		if rangeHeader != "" {
			re := regexp.MustCompile(`bytes=(\d+)-(\d*)`)
			matches := re.FindStringSubmatch(rangeHeader)
			if matches != nil {
				start, _ := strconv.ParseInt(matches[1], 10, 64)
				end := fileSize.Size() - 1
				if matches[2] != "" {
					end, _ = strconv.ParseInt(matches[2], 10, 64)
				}
				length := end - start + 1

				f, err := os.Open(filePath)
				if err != nil {
					http.Error(w, "Internal Server Error", 500)
					return
				}
				defer f.Close()

				f.Seek(start, 0)
				buf := make([]byte, length)
				f.Read(buf)

				w.Header().Set("Content-Type", mimeType)
				w.Header().Set("Content-Range", fmt.Sprintf("bytes %d-%d/%d", start, end, fileSize.Size()))
				w.Header().Set("Accept-Ranges", "bytes")
				w.Header().Set("Content-Length", fmt.Sprintf("%d", length))
				w.Header().Set("Cache-Control", "public, max-age=3600")
				w.WriteHeader(206)
				w.Write(buf)
				return
			}
		}

		w.Header().Set("Content-Type", mimeType)
		w.Header().Set("Accept-Ranges", "bytes")
		w.Header().Set("Content-Length", fmt.Sprintf("%d", fileSize.Size()))
		w.Header().Set("Cache-Control", "public, max-age=3600")
	}

	w.Header().Set("Cache-Control", "public, max-age=3600")
	http.ServeFile(w, r, filePath)
}

// 系统信息API
func handleAPISysInfo(w http.ResponseWriter, r *http.Request) {
	disk := getDiskUsage()
	files := getFileList()

	totalDownloads := float64(0)
	for _, f := range files {
		if count, ok := f["download_count"].(float64); ok {
			totalDownloads += count
		}
	}

	jsonSuccess(w, map[string]interface{}{
		"disk": disk,
		"config": map[string]interface{}{
			"max_file_size":  getConfigFloat("max_file_size"),
			"max_total_size": getConfigFloat("max_total_size"),
			"app_name":       getConfigString("app_name"),
			"app_version":    getConfigString("app_version"),
		},
		"file_count":      len(files),
		"service_start":   serviceStartTime.Format(time.RFC3339),
		"uptime":          time.Since(serviceStartTime).String(),
		"total_downloads": totalDownloads,
	})
}

// 系统配置API
func handleGetSystemConfig(w http.ResponseWriter, r *http.Request) {
	jsonSuccess(w, map[string]interface{}{
		"max_file_size":  getConfigFloat("max_file_size") * 1024 * 1024,
		"max_total_size": getConfigFloat("max_total_size") * 1024 * 1024,
		"app_name":       getConfigString("app_name"),
		"app_version":    getConfigString("app_version"),
	})
}

// 更新配置API
func handleUpdateConfig(w http.ResponseWriter, r *http.Request) {
	var data map[string]interface{}
	if err := json.NewDecoder(r.Body).Decode(&data); err != nil {
		jsonError(w, 400, "无效请求")
		return
	}

	if maxStorage, ok := data["max_storage"].(float64); ok {
		if maxStorage <= 0 {
			jsonError(w, 400, "存储空间必须大于0")
			return
		}
		setConfig("max_total_size", maxStorage*1024)
	}

	if maxFileSize, ok := data["max_file_size"].(float64); ok {
		if maxFileSize <= 0 {
			jsonError(w, 400, "文件大小必须大于0")
			return
		}
		setConfig("max_file_size", maxFileSize)
	}

	if geetestID, ok := data["geetest_id"].(string); ok {
		setConfig("geetest_id", geetestID)
	}
	if geetestKey, ok := data["geetest_key"].(string); ok {
		setConfig("geetest_key", geetestKey)
	}

	if offlineEnabled, ok := data["offline_download_enabled"]; ok {
		switch v := offlineEnabled.(type) {
		case bool:
			setConfig("offline_download_enabled", v)
		case string:
			setConfig("offline_download_enabled", v == "on" || v == "true")
		}
	} else {
		setConfig("offline_download_enabled", false)
	}

	if port, ok := data["port"].(float64); ok {
		p := int(port)
		if p < 1024 || p > 65535 {
			jsonError(w, 400, "端口必须在1024-65535之间")
			return
		}
		setConfig("port", port)
	}

	if netIface, ok := data["network_interface"].(string); ok {
		setConfig("network_interface", netIface)
	}

	saveConfig()
	jsonSuccess(w, map[string]interface{}{
		"config": systemConfig,
	})
}

// 自动更新配置API
func handleUpdateConfigAuto(w http.ResponseWriter, r *http.Request) {
	loadConfig()
	jsonSuccess(w, map[string]interface{}{
		"message": "配置文件已自动更新",
	})
}

// 重启服务器API
func handleRestartServer(w http.ResponseWriter, r *http.Request) {
	if runtime.GOOS == "windows" {
		exePath, _ := os.Executable()
		go func() {
			time.Sleep(2 * time.Second)
			exec.Command("cmd", "/c", "start", exePath).Start()
		}()
		jsonSuccess(w, map[string]interface{}{
			"message": "服务正在重启中...",
		})
		return
	}
	jsonError(w, 400, "当前系统不支持自动重启功能")
}

// GitHub克隆API
func handleAddGitHubClone(w http.ResponseWriter, r *http.Request) {
	cookie, _ := r.Cookie("admin_token")
	if cookie == nil {
		jsonError(w, 403, "未授权访问")
		return
	}
	adminTokensMu.Lock()
	valid := adminTokens[cookie.Value]
	adminTokensMu.Unlock()
	if !valid {
		jsonError(w, 403, "未授权访问")
		return
	}

	if !isGitInstalled() {
		if runtime.GOOS == "windows" {
			if !installGit() {
				jsonError(w, 400, "Git未安装且自动安装失败")
				return
			}
		} else {
			jsonError(w, 400, "Git未安装")
			return
		}
	}

	var data map[string]string
	if err := json.NewDecoder(r.Body).Decode(&data); err != nil {
		jsonError(w, 400, "未提供仓库URL")
		return
	}

	repoURL := data["repo_url"]
	branch := data["branch"]
	if branch == "" {
		branch = "main"
	}
	if repoURL == "" {
		jsonError(w, 400, "未提供仓库URL")
		return
	}

	hash := md5.Sum([]byte(fmt.Sprintf("%s%d", repoURL, time.Now().UnixNano())))
	taskID := hex.EncodeToString(hash[:])[:8]

	cloner := NewGitHubCloner(repoURL, taskID, branch)

	githubCloneTasksMu.Lock()
	githubCloneTasks[taskID] = map[string]interface{}{
		"status":     "pending",
		"progress":   0,
		"repo_url":   repoURL,
		"file_name":  nil,
		"error":      nil,
		"start_time": time.Now().Unix(),
		"branch":     branch,
	}
	githubCloneTasksMu.Unlock()

	githubCloneQueue <- cloner

	jsonSuccess(w, map[string]interface{}{
		"task_id": taskID,
	})
}

// 获取GitHub克隆任务列表
func handleGetGitHubCloneTasks(w http.ResponseWriter, r *http.Request) {
	githubCloneTasksMu.Lock()
	defer githubCloneTasksMu.Unlock()

	var tasks []map[string]interface{}
	for _, task := range githubCloneTasks {
		tasks = append(tasks, task)
	}

	jsonSuccess(w, map[string]interface{}{
		"tasks":         tasks,
		"active_count":  len(githubCloneQueue),
		"thread_active": true,
	})
}

// 取消GitHub克隆任务
func handleCancelGitHubCloneTask(w http.ResponseWriter, r *http.Request) {
	var data map[string]string
	if err := json.NewDecoder(r.Body).Decode(&data); err != nil {
		jsonError(w, 400, "未提供任务ID")
		return
	}

	taskID := data["task_id"]
	if taskID == "" {
		jsonError(w, 400, "未提供任务ID")
		return
	}

	activeClonersMu.Lock()
	if cloner, ok := activeCloners[taskID]; ok {
		cloner.Cancel()
		githubCloneTasksMu.Lock()
		if task, ok := githubCloneTasks[taskID]; ok {
			task["status"] = "cancelled"
		}
		githubCloneTasksMu.Unlock()
		activeClonersMu.Unlock()
		jsonSuccess(w, map[string]interface{}{
			"message": "任务已取消",
		})
		return
	}
	activeClonersMu.Unlock()

	githubCloneTasksMu.Lock()
	if _, ok := githubCloneTasks[taskID]; ok {
		githubCloneTasks[taskID]["status"] = "cancelled"
		githubCloneTasksMu.Unlock()
		jsonSuccess(w, map[string]interface{}{
			"message": "任务已标记为取消",
		})
		return
	}
	githubCloneTasksMu.Unlock()

	jsonError(w, 404, "任务不存在")
}

// 离线下载页面
func handleOfflineDownloadPage(w http.ResponseWriter, r *http.Request) {
	renderTemplate(w, "offline_download.html", pongo2.Context{
		"geetest_id": getConfigString("geetest_id"),
		"app_name":   getConfigString("app_name"),
	})
}

// 添加离线下载任务
func handleAddOfflineDownload(w http.ResponseWriter, r *http.Request) {
	if !getConfigBool("offline_download_enabled") {
		jsonError(w, 403, "离线下载功能未启用")
		return
	}

	var data map[string]interface{}
	if err := json.NewDecoder(r.Body).Decode(&data); err != nil {
		jsonError(w, 400, "无效请求")
		return
	}

	url, _ := data["url"].(string)
	if url == "" || !regexp.MustCompile(`^https?://`).MatchString(url) {
		jsonError(w, 400, "无效的URL")
		return
	}

	// 验证极验
	geetestData, _ := data["geetest"].(map[string]interface{})
	captchaID := getConfigString("geetest_id")
	captchaKey := getConfigString("geetest_key")

	if captchaID == "" || captchaKey == "" {
		jsonError(w, 500, "验证码未配置")
		return
	}

	if geetestData == nil {
		jsonError(w, 400, "验证参数缺失")
		return
	}

	lotNumber, _ := geetestData["lot_number"].(string)
	captchaOutput, _ := geetestData["captcha_output"].(string)
	passToken, _ := geetestData["pass_token"].(string)
	genTime, _ := geetestData["gen_time"].(string)

	if lotNumber == "" || captchaOutput == "" || passToken == "" || genTime == "" {
		jsonError(w, 400, "验证参数缺失")
		return
	}

	// 生成签名
	mac := hmac.New(sha256.New, []byte(captchaKey))
	mac.Write([]byte(lotNumber))
	signToken := hex.EncodeToString(mac.Sum(nil))

	// 验证请求
	validateURL := fmt.Sprintf("https://gcaptcha4.geetest.com/validate?captcha_id=%s", captchaID)
	formData := fmt.Sprintf("lot_number=%s&captcha_output=%s&pass_token=%s&gen_time=%s&sign_token=%s",
		lotNumber, captchaOutput, passToken, genTime, signToken)

	resp, err := http.Post(validateURL, "application/x-www-form-urlencoded", strings.NewReader(formData))
	if err != nil || resp.StatusCode != 200 {
		jsonError(w, 500, "验证服务异常")
		return
	}
	defer resp.Body.Close()

	var result map[string]interface{}
	json.NewDecoder(resp.Body).Decode(&result)
	if result["result"] != "success" {
		jsonError(w, 403, "验证失败")
		return
	}

	// 创建任务
	taskID := generateToken()[:16]
	filename := filepath.Base(url)
	if filename == "" || filename == "." || filename == "/" {
		filename = fmt.Sprintf("download_%d", time.Now().Unix())
	}
	filename = secureFilename(filename)
	if filename == "" {
		filename = fmt.Sprintf("download_%d", time.Now().Unix())
	}

	offlineTasksMu.Lock()
	offlineTasks[taskID] = map[string]interface{}{
		"id":       taskID,
		"url":      url,
		"filename": filename,
		"status":   "queued",
		"progress": 0,
		"created":  time.Now().Format(time.RFC3339),
	}
	offlineTasksMu.Unlock()

	offlineQueue <- taskID

	jsonSuccess(w, map[string]interface{}{
		"task_id": taskID,
		"message": "下载任务已添加",
	})
}

// 获取离线下载任务列表
func handleGetOfflineTasks(w http.ResponseWriter, r *http.Request) {
	offlineTasksMu.Lock()
	defer offlineTasksMu.Unlock()

	var safeTasks []map[string]interface{}
	for _, task := range offlineTasks {
		safeTasks = append(safeTasks, map[string]interface{}{
			"id":       task["id"],
			"url":      task["url"],
			"filename": task["filename"],
			"status":   task["status"],
			"progress": task["progress"],
			"created":  task["created"],
			"error":    task["error"],
		})
	}

	jsonSuccess(w, map[string]interface{}{
		"tasks": safeTasks,
	})
}

// 清空离线任务
func handleClearOfflineTasks(w http.ResponseWriter, r *http.Request) {
	offlineTasksMu.Lock()
	defer offlineTasksMu.Unlock()

	var toDelete []string
	for taskID, task := range offlineTasks {
		status, _ := task["status"].(string)
		if status == "completed" || status == "failed" || status == "cancelled" {
			toDelete = append(toDelete, taskID)
		}
	}
	for _, taskID := range toDelete {
		delete(offlineTasks, taskID)
	}

	jsonSuccess(w, map[string]interface{}{
		"count": len(toDelete),
	})
}

// 取消离线下载任务
func handleCancelOfflineTask(w http.ResponseWriter, r *http.Request) {
	var data map[string]string
	if err := json.NewDecoder(r.Body).Decode(&data); err != nil {
		jsonError(w, 400, "任务ID不能为空")
		return
	}

	taskID := data["task_id"]
	if taskID == "" {
		jsonError(w, 400, "任务ID不能为空")
		return
	}

	offlineTasksMu.Lock()
	task, ok := offlineTasks[taskID]
	offlineTasksMu.Unlock()

	if !ok {
		jsonError(w, 404, "任务不存在")
		return
	}

	status, _ := task["status"].(string)
	if status == "completed" || status == "failed" || status == "cancelled" {
		jsonError(w, 400, fmt.Sprintf("任务已%s，无法取消", status))
		return
	}

	activeDownloaderMu.Lock()
	if downloader, ok := activeDownloaders[taskID]; ok {
		downloader.Cancel()
		offlineTasksMu.Lock()
		offlineTasks[taskID]["status"] = "cancelled"
		offlineTasksMu.Unlock()
		activeDownloaderMu.Unlock()
		jsonSuccess(w, map[string]interface{}{
			"message": "任务已取消",
		})
		return
	}
	activeDownloaderMu.Unlock()

	offlineTasksMu.Lock()
	offlineTasks[taskID]["status"] = "cancelled"
	offlineTasksMu.Unlock()

	jsonSuccess(w, map[string]interface{}{
		"message": "任务已标记为取消",
	})
}

// 文件详情页面
func handleFileDetail(w http.ResponseWriter, r *http.Request) {
	filename := r.URL.Query().Get("file")
	if filename == "" {
		http.Redirect(w, r, "/index", 302)
		return
	}
	renderTemplate(w, "file_detail.html", nil)
}

// 文件信息API
func handleAPIFileInfo(w http.ResponseWriter, r *http.Request) {
	filename := r.URL.Query().Get("filename")
	if filename == "" {
		jsonError(w, 400, "未提供文件名")
		return
	}

	filePath := filepath.Join(getUploadFolder(), filename)
	info, err := os.Stat(filePath)
	if err != nil {
		jsonError(w, 404, "文件不存在")
		return
	}

	metadata := loadMetadata()
	fileMeta := metadata[filename]
	downloadCount := float64(0)
	if fileMeta != nil {
		if count, ok := fileMeta["download_count"].(float64); ok {
			downloadCount = count
		}
	}

	jsonSuccess(w, map[string]interface{}{
		"filename":       filename,
		"size":           float64(info.Size()),
		"created":        float64(info.ModTime().Unix()),
		"modified":       float64(info.ModTime().Unix()),
		"download_count": downloadCount,
	})
}

// PDF信息API
func handleAPIPDFInfo(w http.ResponseWriter, r *http.Request) {
	filename := r.URL.Query().Get("filename")
	if filename == "" {
		jsonError(w, 400, "未提供文件名")
		return
	}

	filePath := filepath.Join(getUploadFolder(), filename)
	if _, err := os.Stat(filePath); os.IsNotExist(err) {
		jsonError(w, 404, "文件不存在")
		return
	}

	// 简单的PDF页数统计（通过搜索/Type /Page）
	data, err := os.ReadFile(filePath)
	if err != nil {
		jsonError(w, 500, fmt.Sprintf("PDF处理失败: %s", err.Error()))
		return
	}

	pageCount := bytes.Count(data, []byte("/Type /Page"))
	// 也搜索 /Type/Page (无空格)
	pageCount += bytes.Count(data, []byte("/Type/Page"))

	jsonSuccess(w, map[string]interface{}{
		"pages": pageCount,
		"metadata": map[string]string{
			"title":             "",
			"author":            "",
			"subject":           "",
			"creator":           "",
			"producer":          "",
			"creation_date":     "",
			"modification_date": "",
		},
	})
}

// 系统日志API
func handleAPISystemLog(w http.ResponseWriter, r *http.Request) {
	logType := r.URL.Query().Get("type")
	if logType == "" {
		logType = "system"
	}
	validTypes := map[string]bool{"system": true, "api": true, "user": true}
	if !validTypes[logType] {
		logType = "system"
	}

	days := 1
	if d, err := strconv.Atoi(r.URL.Query().Get("days")); err == nil {
		days = d
	}
	if days < 1 {
		days = 1
	} else if days > 7 {
		days = 7
	}

	logContent := getLogs(logType, days)
	w.Header().Set("Content-Type", "text/plain; charset=utf-8")
	w.Write([]byte(logContent))
}

// 更新日志页面
func handleChangelog(w http.ResponseWriter, r *http.Request) {
	renderTemplate(w, "changelog.html", nil)
}

// 开源信息页面
func handleOpenSource(w http.ResponseWriter, r *http.Request) {
	renderTemplate(w, "open_source.html", pongo2.Context{
		"app_name":       getConfigString("app_name"),
		"app_version":    getConfigString("app_version"),
		"admin_user":     getConfigString("admin_user"),
		"admin_password": getConfigString("admin_password"),
	})
}

// 错误管理页面
func handleErrorManagement(w http.ResponseWriter, r *http.Request) {
	renderTemplate(w, "error_management.html", pongo2.Context{
		"app_name":    getConfigString("app_name"),
		"app_version": getConfigString("app_version"),
	})
}

// 验证码设置页面
func handleCaptchaSettings(w http.ResponseWriter, r *http.Request) {
	http.Redirect(w, r, "/admin", 302)
}

// 错误页面
func handleErrorPage(template string) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		w.WriteHeader(getStatusCode(template))
		renderTemplate(w, template, nil)
	}
}

func getStatusCode(template string) int {
	switch template {
	case "400.html":
		return 400
	case "403.html":
		return 403
	case "404.html":
		return 404
	case "418.html":
		return 418
	case "500.html":
		return 500
	case "503.html":
		return 503
	default:
		return 200
	}
}

// 检查更新API (简化版)
func handleCheckUpdate(w http.ResponseWriter, r *http.Request) {
	currentVersion := getConfigString("app_version")
	jsonSuccess(w, map[string]interface{}{
		"status":          "no_update",
		"current_version": currentVersion,
		"message":         "当前已是最新版本",
	})
}

// 启动更新API (简化版)
func handleStartUpdate(w http.ResponseWriter, r *http.Request) {
	jsonSuccess(w, map[string]interface{}{
		"status":  "no_update",
		"message": "当前已是最新版本",
	})
}

// 下载更新API (简化版)
func handleDownloadUpdate(w http.ResponseWriter, r *http.Request) {
	jsonError(w, 500, "更新模块不可用")
}

// 应用更新API (简化版)
func handleApplyUpdate(w http.ResponseWriter, r *http.Request) {
	jsonError(w, 500, "更新模块不可用")
}

// 更新后重启API (简化版)
func handleRestartAfterUpdate(w http.ResponseWriter, r *http.Request) {
	handleRestartServer(w, r)
}

// 更新状态API (简化版)
func handleUpdateStatus(w http.ResponseWriter, r *http.Request) {
	jsonSuccess(w, map[string]interface{}{
		"current_version": getConfigString("app_version"),
		"update_info":     nil,
	})
}

// 静态文件服务
func handleStatic(w http.ResponseWriter, r *http.Request) {
	fs := http.FileServer(http.Dir("static"))
	http.StripPrefix("/static/", fs).ServeHTTP(w, r)
}

// ==============================================
// 主函数
// ==============================================

func main() {
	serviceStartTime = time.Now()

	// 初始化配置
	systemConfig = make(map[string]interface{})
	for k, v := range DefaultConfig {
		systemConfig[k] = v
	}

	// 初始化日志
	initLogging()

	// 初始化系统
	initSystem()

	// 启动工作线程
	startGitHubCloneWorker()
	startOfflineDownloadWorker()

	// 检查重启标志
	restartFlagPath := filepath.Join(filepath.Dir(os.Args[0]), ".restart_flag")
	if _, err := os.Stat(restartFlagPath); err == nil {
		os.Remove(restartFlagPath)
		logSystem("检测到重启标志文件，已清理并准备重启...")
	}

	os.MkdirAll(getUploadFolder(), 0755)

	// 注册路由
	mux := http.NewServeMux()

	// 静态文件
	mux.HandleFunc("/static/", handleStatic)
	mux.HandleFunc("/favicon.ico", func(w http.ResponseWriter, r *http.Request) {
		http.ServeFile(w, r, "static/favicon.ico")
	})

	// 页面路由
	mux.HandleFunc("/", handleDownloadPage)
	mux.HandleFunc("/index", handleIndex)
	mux.HandleFunc("/admin", handleAdmin)
	mux.HandleFunc("/admin/login", func(w http.ResponseWriter, r *http.Request) {
		if r.Method == "GET" {
			handleAdminLoginGet(w, r)
		} else if r.Method == "POST" {
			handleAdminLoginPost(w, r)
		}
	})
	mux.HandleFunc("/admin/logout", handleAdminLogout)
	mux.HandleFunc("/admin/change_password", requireAdminToken(func(w http.ResponseWriter, r *http.Request) {
		if r.Method == "POST" {
			handleAdminChangePassword(w, r)
		}
	}))
	mux.HandleFunc("/admin/github_clone", handleAdminGitHubClone)
	mux.HandleFunc("/captcha_settings", requireAdminToken(handleCaptchaSettings))

	// 文件操作
	mux.HandleFunc("/download/{filename...}", handleDownload)
	mux.HandleFunc("/preview/{filename...}", handlePreview)

	// API路由
	mux.HandleFunc("/api/files", handleAPIFiles)
	mux.HandleFunc("/api/upload", func(w http.ResponseWriter, r *http.Request) {
		if r.Method == "POST" {
			handleUpload(w, r)
		}
	})
	mux.HandleFunc("/api/delete_file", requireAdminToken(func(w http.ResponseWriter, r *http.Request) {
		if r.Method == "POST" {
			handleAPIDeleteFile(w, r)
		}
	}))

	// 多文件上传
	mux.HandleFunc("/multi_upload", handleMultiUploadPage)
	mux.HandleFunc("/api/multi_upload", func(w http.ResponseWriter, r *http.Request) {
		if r.Method == "POST" {
			handleMultiUpload(w, r)
		}
	})

	// GitHub克隆
	mux.HandleFunc("/api/github_clone", func(w http.ResponseWriter, r *http.Request) {
		if r.Method == "POST" {
			handleAddGitHubClone(w, r)
		}
	})
	mux.HandleFunc("/api/github_clone/tasks", func(w http.ResponseWriter, r *http.Request) {
		if r.Method == "GET" {
			handleGetGitHubCloneTasks(w, r)
		}
	})
	mux.HandleFunc("/api/github_clone/cancel_task", func(w http.ResponseWriter, r *http.Request) {
		if r.Method == "POST" {
			handleCancelGitHubCloneTask(w, r)
		}
	})

	// 系统信息
	mux.HandleFunc("/api/sysinfo", handleAPISysInfo)
	mux.HandleFunc("/api/system/config", handleGetSystemConfig)
	mux.HandleFunc("/api/update_config", requireAdminToken(func(w http.ResponseWriter, r *http.Request) {
		if r.Method == "POST" {
			handleUpdateConfig(w, r)
		}
	}))
	mux.HandleFunc("/api/update_config_auto", requireAdminToken(func(w http.ResponseWriter, r *http.Request) {
		if r.Method == "POST" {
			handleUpdateConfigAuto(w, r)
		}
	}))
	mux.HandleFunc("/api/restart_server", requireAdminToken(func(w http.ResponseWriter, r *http.Request) {
		if r.Method == "POST" {
			handleRestartServer(w, r)
		}
	}))

	// 更新相关
	mux.HandleFunc("/api/check_update", requireAdminToken(handleCheckUpdate))
	mux.HandleFunc("/api/start_update", requireAdminToken(handleStartUpdate))
	mux.HandleFunc("/api/download_update", requireAdminToken(handleDownloadUpdate))
	mux.HandleFunc("/api/apply_update", requireAdminToken(handleApplyUpdate))
	mux.HandleFunc("/api/restart_after_update", requireAdminToken(handleRestartAfterUpdate))
	mux.HandleFunc("/api/update_status", requireAdminToken(handleUpdateStatus))

	// 系统日志
	mux.HandleFunc("/api/system_log", requireAdminToken(handleAPISystemLog))

	// 离线下载
	mux.HandleFunc("/offline_download", handleOfflineDownloadPage)
	mux.HandleFunc("/api/offline_download", func(w http.ResponseWriter, r *http.Request) {
		if r.Method == "POST" {
			handleAddOfflineDownload(w, r)
		}
	})
	mux.HandleFunc("/api/offline_tasks", func(w http.ResponseWriter, r *http.Request) {
		if r.Method == "GET" {
			handleGetOfflineTasks(w, r)
		}
	})
	mux.HandleFunc("/api/offline_tasks/clear", func(w http.ResponseWriter, r *http.Request) {
		if r.Method == "POST" {
			handleClearOfflineTasks(w, r)
		}
	})
	mux.HandleFunc("/api/offline_tasks/cancel", func(w http.ResponseWriter, r *http.Request) {
		if r.Method == "POST" {
			handleCancelOfflineTask(w, r)
		}
	})

	// 文件详情
	mux.HandleFunc("/file_detail", handleFileDetail)
	mux.HandleFunc("/api/file_info", handleAPIFileInfo)

	// PDF
	mux.HandleFunc("/api/pdf_info", handleAPIPDFInfo)

	// 其他页面
	mux.HandleFunc("/changelog", handleChangelog)
	mux.HandleFunc("/open_source", handleOpenSource)
	mux.HandleFunc("/error_management", requireAdminToken(handleErrorManagement))

	// 错误页面
	mux.HandleFunc("/400", handleErrorPage("400.html"))
	mux.HandleFunc("/403", handleErrorPage("403.html"))
	mux.HandleFunc("/404", handleErrorPage("404.html"))
	mux.HandleFunc("/418", handleErrorPage("418.html"))
	mux.HandleFunc("/500", handleErrorPage("500.html"))
	mux.HandleFunc("/503", handleErrorPage("503.html"))

	// 打印启动信息
	port := getConfigInt("port")
	logSystem("服务已启动")
	logSystem("应用名称: %s v%s", getConfigString("app_name"), getConfigString("app_version"))
	logSystem("上传目录: %s", getUploadFolder())
	logSystem("总空间上限: %s", convertSize(getConfigFloat("max_total_size")*1024*1024))
	logSystem("服务启动时间: %s", serviceStartTime.Format("2006-01-02 15:04:05"))
	logSystem("主服务端口: %d", port)
	logSystem("")
	logSystem("访问地址: http://localhost:%d/index", port)
	logSystem("管理页面: http://localhost:%d/admin/login", port)
	logSystem("纯下载页面: http://localhost:%d/", port)

	// 检查更新
	currentVersion := getConfigString("app_version")
	if currentVersion != "EXE_ENVIRONMENT" {
		updateInfo := checkForUpdates(currentVersion)
		if updateInfo["status"] == "update_available" {
			logSystem("\n发现新版本! 当前版本: %s, 最新版本: %s", updateInfo["current_version"], updateInfo["latest_version"])
		} else {
			logSystem("当前已是最新版本。")
		}
	} else {
		logSystem("检测到可执行文件环境，自动更新功能已禁用。")
	}

	logSystem("启动后,请到管理员页面配置密码,以生成配置文件")
	logSystem("请管理员尽快到配置文件中配置极验,以便使用离线下载功能")

	addr := fmt.Sprintf("0.0.0.0:%d", port)
	logSystem("服务器监听地址: %s", addr)
	if err := http.ListenAndServe(addr, mux); err != nil {
		log.Fatalf("服务器启动失败: %v", err)
	}
}

// checkForUpdates 检查更新 (简化版)
func checkForUpdates(currentVersion string) map[string]string {
	// 简化实现，返回无更新
	return map[string]string{
		"status":          "no_update",
		"current_version": currentVersion,
		"message":         "当前已是最新版本",
	}
}
