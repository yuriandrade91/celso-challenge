import Dashboard from "@/components/Dashboard";
import SessionRefresh from "@/components/SessionRefresh";
import {
  ACCESS_TOKEN_COOKIE,
  getBackendUser,
  REFRESH_TOKEN_COOKIE,
} from "@/lib/auth-session";
import { cookies } from "next/headers";

export const instant = false;

export default async function Home() {
  const cookieStore = await cookies();
  const accessToken = cookieStore.get(ACCESS_TOKEN_COOKIE)?.value;
  const hasRefreshToken = cookieStore.has(REFRESH_TOKEN_COOKIE);

  if (!accessToken) {
    return hasRefreshToken ? (
      <SessionRefresh />
    ) : (
      <Dashboard initialUser={null} />
    );
  }

  const user = await getBackendUser(accessToken);
  if (user) return <Dashboard initialUser={user} />;

  return hasRefreshToken ? (
    <SessionRefresh />
  ) : (
    <Dashboard initialUser={null} />
  );
}
