import LoginScreen from "./components/layout/LoginScreen/LoginScreen";
import WakeScreen from "./components/layout/WakeScreen/WakeScreen";
import { useServerWake } from "./hooks/useServerWake";
import { useSession } from "./hooks/useSession";
import Workspace from "./Workspace";

/** כניסה לאפליקציה: מחכה שהשרת יתעורר, מסך כניסה (אם השרת דורש), ואז מסך העבודה. */
export default function App() {
  const server = useServerWake();
  const session = useSession(server.status === "ready");

  if (server.status !== "ready") return <WakeScreen status={server.status} onRetry={server.retry} />;
  if (session.status === "checking") return <WakeScreen status="connecting" onRetry={server.retry} />;
  if (session.status === "login") return <LoginScreen demo={session.session?.demo ?? null} onLogin={session.login} />;
  return <Workspace dbOk={server.dbOk} onLogout={session.canLogout ? session.logout : null} />;
}
