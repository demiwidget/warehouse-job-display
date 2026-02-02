import { useState, useEffect } from "react";
import { trpc } from "@/lib/trpc";
import { Button } from "@/components/ui/button";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Card } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { toast } from "sonner";

export function DisplaySettings() {
  const [selectedArea, setSelectedArea] = useState<string>("");
  const [settings, setSettings] = useState<{
    refreshIntervalSeconds: number;
    theme: "dark" | "light";
    showLoadTime: number;
    showJobNumber: number;
    showJobTitle: number;
    fontSize: "small" | "medium" | "large" | "xlarge";
  }>({
    refreshIntervalSeconds: 30,
    theme: "dark",
    showLoadTime: 1,
    showJobNumber: 1,
    showJobTitle: 1,
    fontSize: "xlarge",
  });

  const { data: areas } = trpc.warehouse.listAreas.useQuery();
  const { data: displaySettings } = trpc.warehouse.getDisplaySettings.useQuery(
    { areaId: parseInt(selectedArea) },
    { enabled: !!selectedArea }
  );

  const updateMutation = trpc.warehouse.updateDisplaySettings.useMutation({
    onSuccess: () => {
      toast.success("Settings updated successfully");
    },
    onError: (error) => {
      toast.error(error.message || "Failed to update settings");
    },
  });

  useEffect(() => {
    if (displaySettings) {
      setSettings({
        refreshIntervalSeconds: displaySettings.refreshIntervalSeconds,
        theme: displaySettings.theme,
        showLoadTime: displaySettings.showLoadTime,
        showJobNumber: displaySettings.showJobNumber,
        showJobTitle: displaySettings.showJobTitle,
        fontSize: displaySettings.fontSize,
      });
    }
  }, [displaySettings]);

  const handleSave = () => {
    if (!selectedArea) {
      toast.error("Please select an area first");
      return;
    }
    updateMutation.mutate({
      areaId: parseInt(selectedArea),
      ...settings,
    });
  };

  return (
    <div className="space-y-6">
      {/* Area Selection */}
      <div>
        <label className="block text-sm font-medium text-slate-300 mb-2">Select Area</label>
        <Select value={selectedArea} onValueChange={setSelectedArea}>
          <SelectTrigger className="bg-slate-800 border-slate-600 text-white">
            <SelectValue placeholder="Choose an area..." />
          </SelectTrigger>
          <SelectContent className="bg-slate-800 border-slate-600">
            {areas?.map((area) => (
              <SelectItem key={area.id} value={String(area.id)} className="text-white">
                {area.displayName}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      </div>

      {selectedArea && (
        <div className="space-y-6">
          {/* Refresh Interval */}
          <div>
            <Label className="text-slate-300 mb-2 block">Refresh Interval (seconds)</Label>
            <Input
              type="number"
              min="5"
              max="300"
              step="5"
              value={settings.refreshIntervalSeconds}
              onChange={(e) =>
                setSettings({ ...settings, refreshIntervalSeconds: parseInt(e.target.value) })
              }
              className="bg-slate-800 border-slate-600 text-white"
            />
            <p className="text-xs text-slate-400 mt-1">
              How often to refresh job data from Current-RMS
            </p>
          </div>

          {/* Theme */}
          <div>
            <Label className="text-slate-300 mb-2 block">Theme</Label>
            <Select value={settings.theme} onValueChange={(value: "dark" | "light") => setSettings({ ...settings, theme: value })}>
              <SelectTrigger className="bg-slate-800 border-slate-600 text-white">
                <SelectValue />
              </SelectTrigger>
              <SelectContent className="bg-slate-800 border-slate-600">
                <SelectItem value="dark" className="text-white">Dark</SelectItem>
                <SelectItem value="light" className="text-white">Light</SelectItem>
              </SelectContent>
            </Select>
          </div>

          {/* Font Size */}
          <div>
            <Label className="text-slate-300 mb-2 block">Font Size</Label>
            <Select value={settings.fontSize} onValueChange={(value: "small" | "medium" | "large" | "xlarge") => setSettings({ ...settings, fontSize: value })}>
              <SelectTrigger className="bg-slate-800 border-slate-600 text-white">
                <SelectValue />
              </SelectTrigger>
              <SelectContent className="bg-slate-800 border-slate-600">
                <SelectItem value="small" className="text-white">Small</SelectItem>
                <SelectItem value="medium" className="text-white">Medium</SelectItem>
                <SelectItem value="large" className="text-white">Large</SelectItem>
                <SelectItem value="xlarge" className="text-white">Extra Large</SelectItem>
              </SelectContent>
            </Select>
            <p className="text-xs text-slate-400 mt-1">
              Larger fonts are easier to read from a distance
            </p>
          </div>

          {/* Display Options */}
          <Card className="p-4 border-slate-700 bg-slate-700/30">
            <h4 className="font-medium text-white mb-4">Display Options</h4>
            <div className="space-y-3">
              <label className="flex items-center gap-3 cursor-pointer">
                <input
                  type="checkbox"
                  checked={settings.showJobTitle === 1}
                  onChange={(e) =>
                    setSettings({ ...settings, showJobTitle: e.target.checked ? 1 : 0 })
                  }
                  className="w-4 h-4 rounded border-slate-600 bg-slate-800 text-blue-600"
                />
                <span className="text-slate-300">Show Job Title</span>
              </label>
              <label className="flex items-center gap-3 cursor-pointer">
                <input
                  type="checkbox"
                  checked={settings.showJobNumber === 1}
                  onChange={(e) =>
                    setSettings({ ...settings, showJobNumber: e.target.checked ? 1 : 0 })
                  }
                  className="w-4 h-4 rounded border-slate-600 bg-slate-800 text-blue-600"
                />
                <span className="text-slate-300">Show Job Number</span>
              </label>
              <label className="flex items-center gap-3 cursor-pointer">
                <input
                  type="checkbox"
                  checked={settings.showLoadTime === 1}
                  onChange={(e) =>
                    setSettings({ ...settings, showLoadTime: e.target.checked ? 1 : 0 })
                  }
                  className="w-4 h-4 rounded border-slate-600 bg-slate-800 text-blue-600"
                />
                <span className="text-slate-300">Show Load Date & Time</span>
              </label>
            </div>
          </Card>

          {/* Save Button */}
          <Button
            onClick={handleSave}
            disabled={updateMutation.isPending}
            className="w-full bg-blue-600 hover:bg-blue-700"
          >
            {updateMutation.isPending ? "Saving..." : "Save Settings"}
          </Button>
        </div>
      )}
    </div>
  );
}
