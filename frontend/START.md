# MorningEdge 启动指南

## 快速启动步骤

### 1. 打开终端（Terminal/PowerShell）

在项目根目录 `Morning_Edge` 下打开终端。

### 2. 进入 frontend 目录

```bash
cd frontend
```

### 3. 安装依赖（如果还没安装）

```bash
npm install
```

> **注意**：如果 `node_modules` 文件夹已存在，可以跳过此步骤。

### 4. 启动开发服务器

```bash
npm run dev
```

### 5. 在浏览器中打开

启动成功后，终端会显示类似以下信息：

```
  VITE v6.2.0  ready in xxx ms

  ➜  Local:   http://localhost:3000/
  ➜  Network: use --host to expose
```

**在浏览器中访问：** `http://localhost:3000`

---

## 其他有用的命令

### 构建生产版本
```bash
npm run build
```

### 预览生产版本
```bash
npm run preview
```

---

## 常见问题

### 端口 3000 已被占用？
如果端口 3000 被占用，Vite 会自动尝试下一个可用端口（如 3001, 3002 等）。

### 需要停止服务器？
在终端中按 `Ctrl + C` 停止开发服务器。

### 修改代码后页面没有更新？
Vite 支持热模块替换（HMR），修改代码后页面会自动刷新。如果没有，请手动刷新浏览器。
