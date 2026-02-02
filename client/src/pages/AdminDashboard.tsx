import { useState } from "react";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { AreasManager } from "@/components/warehouse/AreasManager";
import { JobMappings } from "@/components/warehouse/JobMappings";
import { DisplaySettings } from "@/components/warehouse/DisplaySettings";
import { ConnectionTest } from "@/components/warehouse/ConnectionTest";
import { Monitor, Settings, Zap } from "lucide-react";

export default function AdminDashboard() {
  const [activeTab, setActiveTab] = useState("areas");

  return (
    <div className="min-h-screen bg-gradient-to-br from-slate-900 via-slate-800 to-slate-900 p-6">
      <div className="max-w-7xl mx-auto">
        {/* Header */}
        <div className="mb-8">
          <div className="flex items-center gap-3 mb-2">
            <Monitor className="w-8 h-8 text-blue-400" />
            <h1 className="text-4xl font-bold text-white">Warehouse Job Display</h1>
          </div>
          <p className="text-slate-400">Configure display areas and job mappings</p>
        </div>

        {/* Connection Status Card */}
        <div className="mb-8">
          <ConnectionTest />
        </div>

        {/* Main Tabs */}
        <Tabs value={activeTab} onValueChange={setActiveTab} className="w-full">
          <TabsList className="grid w-full grid-cols-3 mb-8 bg-slate-800 border border-slate-700">
            <TabsTrigger value="areas" className="flex items-center gap-2">
              <Monitor className="w-4 h-4" />
              Areas
            </TabsTrigger>
            <TabsTrigger value="mappings" className="flex items-center gap-2">
              <Zap className="w-4 h-4" />
              Job Mappings
            </TabsTrigger>
            <TabsTrigger value="settings" className="flex items-center gap-2">
              <Settings className="w-4 h-4" />
              Display Settings
            </TabsTrigger>
          </TabsList>

          {/* Areas Tab */}
          <TabsContent value="areas" className="space-y-6">
            <Card className="border-slate-700 bg-slate-800">
              <CardHeader>
                <CardTitle className="text-white">Warehouse Areas</CardTitle>
                <CardDescription>
                  Create and manage warehouse display areas
                </CardDescription>
              </CardHeader>
              <CardContent>
                <AreasManager />
              </CardContent>
            </Card>
          </TabsContent>

          {/* Job Mappings Tab */}
          <TabsContent value="mappings" className="space-y-6">
            <Card className="border-slate-700 bg-slate-800">
              <CardHeader>
                <CardTitle className="text-white">Job Mappings</CardTitle>
                <CardDescription>
                  Assign jobs to display areas
                </CardDescription>
              </CardHeader>
              <CardContent>
                <JobMappings />
              </CardContent>
            </Card>
          </TabsContent>

          {/* Display Settings Tab */}
          <TabsContent value="settings" className="space-y-6">
            <Card className="border-slate-700 bg-slate-800">
              <CardHeader>
                <CardTitle className="text-white">Display Settings</CardTitle>
                <CardDescription>
                  Configure display appearance and refresh rates
                </CardDescription>
              </CardHeader>
              <CardContent>
                <DisplaySettings />
              </CardContent>
            </Card>
          </TabsContent>
        </Tabs>

        {/* Footer Info */}
        <div className="mt-12 pt-8 border-t border-slate-700">
          <div className="grid grid-cols-1 md:grid-cols-3 gap-6 text-sm text-slate-400">
            <div>
              <h3 className="font-semibold text-slate-300 mb-2">Display View</h3>
              <p>Access the full-screen display at <code className="bg-slate-900 px-2 py-1 rounded text-blue-300">/display/:areaId</code></p>
            </div>
            <div>
              <h3 className="font-semibold text-slate-300 mb-2">Real-time Updates</h3>
              <p>Jobs update automatically based on your configured refresh interval</p>
            </div>
            <div>
              <h3 className="font-semibold text-slate-300 mb-2">Multiple Screens</h3>
              <p>Deploy different areas to different warehouse screens</p>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
