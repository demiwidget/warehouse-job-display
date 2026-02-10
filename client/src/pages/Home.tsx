import { useState } from "react";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Monitor, Settings, LogOut, AlertCircle, Loader2 } from "lucide-react";
import { useLocation } from "wouter";
import { trpc } from "@/lib/trpc";

export default function Home() {
  const [, setLocation] = useLocation();
  const [mode, setMode] = useState<"login" | "register" | "authenticated">("login");
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [email, setEmail] = useState("");
  const [error, setError] = useState("");
  const [isLoading, setIsLoading] = useState(false);

  const { data: hasUsers } = trpc.auth.hasAdminUsers.useQuery();
  const loginMutation = trpc.auth.login.useMutation();
  const registerMutation = trpc.auth.register.useMutation();
  const logoutMutation = trpc.auth.logout.useMutation();
  const { data: session } = trpc.auth.me.useQuery();

  // Determine initial mode based on whether admin users exist
  if (mode === "login" && hasUsers === false) {
    setMode("register");
  }

  const handleLogin = async (e: React.FormEvent) => {
    e.preventDefault();
    setError("");
    setIsLoading(true);

    try {
      await loginMutation.mutateAsync({ username, password });
      setMode("authenticated");
      setLocation("/admin");
    } catch (err: any) {
      setError(err.message || "Login failed");
    } finally {
      setIsLoading(false);
    }
  };

  const handleRegister = async (e: React.FormEvent) => {
    e.preventDefault();
    setError("");
    setIsLoading(true);

    try {
      await registerMutation.mutateAsync({ username, password, email: email || undefined });
      setMode("authenticated");
      setLocation("/admin");
    } catch (err: any) {
      setError(err.message || "Registration failed");
    } finally {
      setIsLoading(false);
    }
  };

  const handleLogout = async () => {
    setIsLoading(true);
    try {
      await logoutMutation.mutateAsync();
      setMode("login");
      setUsername("");
      setPassword("");
      setEmail("");
    } finally {
      setIsLoading(false);
    }
  };

  // Show authenticated view
  if (session?.authenticated) {
    return (
      <div className="min-h-screen bg-gradient-to-br from-slate-900 via-slate-800 to-slate-900 p-6">
        <div className="max-w-4xl mx-auto">
          <div className="flex items-center justify-between mb-8">
            <div className="flex items-center gap-3">
              <Monitor className="w-8 h-8 text-blue-400" />
              <h1 className="text-3xl font-bold text-white">Warehouse Job Display</h1>
            </div>
            <Button
              variant="outline"
              onClick={handleLogout}
              disabled={isLoading}
              className="border-slate-600 text-slate-300 hover:bg-slate-700 gap-2"
            >
              <LogOut className="w-4 h-4" />
              Sign Out
            </Button>
          </div>

          <Card className="mb-8 p-6 border-slate-700 bg-slate-800">
            <h2 className="text-xl font-semibold text-white mb-2">Welcome to Admin Dashboard!</h2>
            <p className="text-slate-400">
              Configure your warehouse display areas and job mappings to show live Current-RMS job
              data on screens throughout your facility.
            </p>
          </Card>

          <div className="mt-8 text-center">
            <Button
              onClick={() => setLocation("/admin")}
              className="bg-blue-600 hover:bg-blue-700 gap-2 text-lg px-8 py-6"
            >
              <Settings className="w-5 h-5" />
              Go to Admin Dashboard
            </Button>
          </div>
        </div>
      </div>
    );
  }

  // Show login/register form
  return (
    <div className="min-h-screen bg-gradient-to-br from-slate-900 via-slate-800 to-slate-900 flex items-center justify-center p-4">
      <Card className="max-w-md w-full p-8 border-slate-700 bg-slate-800">
        <div className="text-center mb-8">
          <Monitor className="w-16 h-16 text-blue-400 mx-auto mb-4" />
          <h1 className="text-3xl font-bold text-white mb-2">Warehouse Job Display</h1>
          <p className="text-slate-400">
            {mode === "register"
              ? "Create your admin account"
              : "Sign in to manage displays"}
          </p>
        </div>

        {error && (
          <div className="mb-4 p-3 bg-red-900/20 border border-red-700 rounded-lg flex gap-2">
            <AlertCircle className="w-5 h-5 text-red-400 flex-shrink-0 mt-0.5" />
            <p className="text-red-300 text-sm">{error}</p>
          </div>
        )}

        <form onSubmit={mode === "register" ? handleRegister : handleLogin} className="space-y-4">
          <div>
            <label className="block text-sm font-medium text-slate-300 mb-2">Username</label>
            <Input
              type="text"
              value={username}
              onChange={(e) => setUsername(e.target.value)}
              placeholder="Enter username"
              disabled={isLoading}
              className="bg-slate-700 border-slate-600 text-white placeholder-slate-400"
              required
            />
          </div>

          {mode === "register" && (
            <div>
              <label className="block text-sm font-medium text-slate-300 mb-2">
                Email (optional)
              </label>
              <Input
                type="email"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                placeholder="Enter email"
                disabled={isLoading}
                className="bg-slate-700 border-slate-600 text-white placeholder-slate-400"
              />
            </div>
          )}

          <div>
            <label className="block text-sm font-medium text-slate-300 mb-2">Password</label>
            <Input
              type="password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              placeholder="Enter password"
              disabled={isLoading}
              className="bg-slate-700 border-slate-600 text-white placeholder-slate-400"
              required
            />
          </div>

          <Button
            type="submit"
            disabled={isLoading}
            className="w-full bg-blue-600 hover:bg-blue-700 gap-2"
          >
            {isLoading && <Loader2 className="w-4 h-4 animate-spin" />}
            {mode === "register" ? "Create Account" : "Sign In"}
          </Button>
        </form>

        {mode === "login" && hasUsers && (
          <p className="text-center text-slate-400 text-sm mt-4">
            Don't have an account?{" "}
            <button
              onClick={() => setMode("register")}
              className="text-blue-400 hover:text-blue-300 font-medium"
            >
              Contact administrator
            </button>
          </p>
        )}
      </Card>
    </div>
  );
}
