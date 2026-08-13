import "dotenv/config";
import { loadConfig } from "./config.js";
import { CursorSdkProvider } from "./cursor/client.js";
import { createHttpServer } from "./server.js";

const config = loadConfig();
const { app, logger } = createHttpServer(config, new CursorSdkProvider());

app.listen(config.PORT, () => {
  logger.info({ event: "bridge_started", port: config.PORT, transport: "streamable_http" });
});
