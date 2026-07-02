import express, { Request, Response } from "express";
import path from "path";
import { createServer as createViteServer } from "vite";
import { spawn, ChildProcess } from "child_process";
import { createProxyMiddleware } from "http-proxy-middleware";
import fs from "fs";

async function startServer() {
  const app = express();
  const PORT = 3000;
  const BACKEND_PORT = 8000;

  let orchestratorProcess: ChildProcess | null = null;
  let backendProcess: ChildProcess | null = null;
  
  const serviceStatus: Record<string, string> = {
    soul: "stopped",
    vocal: "stopped",
    logic: "stopped",
    emotion: "stopped",
    backend: "starting"
  };

  const startBackend = () => {
    const pythonExe = process.platform === "win32" ? "python" : "python3";
    console.log(`[BACKEND]: Starting FastAPI at port ${BACKEND_PORT}...`);
    
    const appPath = path.join(process.cwd(), "app", "main.py");
    if (!fs.existsSync(appPath)) {
      console.error("[BACKEND]: app/main.py not found!");
      serviceStatus.backend = "error: main.py not found";
      return;
    }

    backendProcess = spawn(pythonExe, ["-m", "app.main"], {
      stdio: "pipe",
      env: {
        ...process.env,
        PORT: BACKEND_PORT.toString(),
        HOST: "127.0.0.1"
      }
    });

    backendProcess.stdout?.on("data", (data: Buffer) => {
      const output = data.toString();
      console.log(`[BACKEND]: ${output}`);
      if (output.includes("Application startup complete")) {
        serviceStatus.backend = "running";
      }
    });

    backendProcess.stderr?.on("data", (data: Buffer) => {
      console.error(`[BACKEND-ERR]: ${data.toString()}`);
    });

    backendProcess.on("close", (code: number) => {
      console.log(`Backend exited with code ${code}`);
      serviceStatus.backend = "stopped";
      if (code !== 0) {
        setTimeout(startBackend, 5000);
      }
    });
  };

  startBackend();

  app.use("/api/v1", createProxyMiddleware({
    target: `http://127.0.0.1:${BACKEND_PORT}`,
    changeOrigin: true,
  }));

  app.use("/chat", createProxyMiddleware({
    target: `http://127.0.0.1:${BACKEND_PORT}`,
    changeOrigin: true,
  }));

  app.use("/health", createProxyMiddleware({
    target: `http://127.0.0.1:${BACKEND_PORT}`,
    changeOrigin: true,
  }));

  app.use("/user", createProxyMiddleware({
    target: `http://127.0.0.1:${BACKEND_PORT}`,
    changeOrigin: true,
  }));

  app.get("/xier", (req: Request, res: Response) => {
    res.sendFile(path.join(process.cwd(), "public", "chat.html"));
  });

  app.get("/api/health", (req: Request, res: Response) => {
    res.json({
      status: "ok",
      services: serviceStatus,
      orchestrator: orchestratorProcess ? "running" : "stopped",
      platform: process.platform,
      python: process.platform === "win32" ? "python" : "python3"
    });
  });

  app.get("/api/status", (req: Request, res: Response) => {
    res.redirect("/api/health");
  });

  app.post("/api/deploy", (req: Request, res: Response) => {
    if (orchestratorProcess) {
      return res.status(400).json({ error: "Orchestrator already running" });
    }

    const pythonExe = process.platform === "win32" ? "python" : "python3";
    orchestratorProcess = spawn(pythonExe, ["seele_v8_5.py", "--action", "deploy"], {
      stdio: "pipe"
    });

    orchestratorProcess.stdout?.on("data", (data: Buffer) => {
      const output = data.toString();
      console.log(`[ORCHESTRATOR]: ${output}`);

      const successMatch = output.match(/\[SUCCESS\] (\w+) started/);
      if (successMatch) {
        serviceStatus[successMatch[1]] = "running";
      }

      const progressMatch = output.match(/\[PROGRESS\] (\d+)\/(\d+) started services ready/);
      if (progressMatch) {
        serviceStatus.progress = `${progressMatch[1]}/${progressMatch[2]}`;
      }

      const errorMatch = output.match(/(?:crashed immediately|\[FAILED\] (?:CRITICAL service )?(\w+))/);
      if (errorMatch && errorMatch[1]) {
        serviceStatus[errorMatch[1]] = "error";
      }
    });

    orchestratorProcess.stderr?.on("data", (data: Buffer) => {
      console.error(`[ORCHESTRATOR-ERR]: ${data.toString()}`);
    });

    orchestratorProcess.on("close", (code: number) => {
      console.log(`Orchestrator exited with code ${code}`);
      orchestratorProcess = null;
    });

    res.json({ message: "Deployment started" });
  });

  if (process.env.NODE_ENV !== "production") {
    const vite = await createViteServer({
      server: { middlewareMode: true },
      appType: "spa",
    });
    app.use(vite.middlewares);
  } else {
    const distPath = path.join(process.cwd(), "dist");
    app.use(express.static(distPath));
    app.get("*", (req: Request, res: Response) => {
      res.sendFile(path.join(distPath, "index.html"));
    });
  }

  app.listen(PORT, "0.0.0.0", () => {
    console.log(`Server running on http://localhost:${PORT}`);
    console.log(`FastAPI running on http://localhost:${BACKEND_PORT}`);
    console.log(`Xier Chat UI at http://localhost:${PORT}/xier`);
  });
}

startServer().catch(error => {
  console.error("Server startup failed:", error);
  process.exit(1);
});