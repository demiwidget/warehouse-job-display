import { useAuth } from "@/_core/hooks/useAuth";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Monitor, Settings, LogOut } from "lucide-react";
import { getLoginUrl } from "@/const";
import { useLocation } from "wouter";

export default function Home() {
  const [, setLocation] = useLocation();
  const { user, isAuthenticated, logout } = useAuth();

  if (!isAuthenticated) {
    return (
      <div className="min-h-screen bg-gradient-to-br from-slate-900 via-slate-800 to-slate-900 flex items-center justify-center p-4">
        <Card className="max-w-md w-full p-8 border-slate-700 bg-slate-800">
          <div className="text-center">
            <Monitor className="w-16 h-16 text-blue-400 mx-auto mb-4" />
            <h1 className="text-3xl font-bold text-white mb-2">Warehouse Job Display</h1>
            <p className="text-slate-400 mb-6">
              Configure and manage warehouse display screens for Current-RMS jobs
            </p>
            <a href={getLoginUrl()}>
              <Button className="w-full bg-blue-600 hover:bg-blue-700">
                Sign In to Get Started
              </Button>
            </a>
          </div>
        </Card>
      </div>
    );
  }

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
            onClick={logout}
            className="border-slate-600 text-slate-300 hover:bg-slate-700 gap-2"
          >
            <LogOut className="w-4 h-4" />
            Sign Out
          </Button>
        </div>

        <Card className="mb-8 p-6 border-slate-700 bg-slate-800">
          <h2 className="text-xl font-semibold text-white mb-2">Welcome, {user?.name}!</h2>
          <p className="text-slate-400">
            Configure your warehouse display areas and job mappings to show live Current-RMS job data
            on screens throughout your facility.
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
