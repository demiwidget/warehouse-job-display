import { useState } from "react";
import { trpc } from "@/lib/trpc";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Card } from "@/components/ui/card";
import { Plus, Trash2, Edit2, Eye } from "lucide-react";
import { toast } from "sonner";
import { useLocation } from "wouter";

export function AreasManager() {
  const [, setLocation] = useLocation();
  const [showForm, setShowForm] = useState(false);
  const [formData, setFormData] = useState({ name: "", displayName: "", description: "" });

  const { data: areas, isLoading, refetch } = trpc.warehouse.listAreas.useQuery();
  const createMutation = trpc.warehouse.createArea.useMutation({
    onSuccess: () => {
      toast.success("Area created successfully");
      setFormData({ name: "", displayName: "", description: "" });
      setShowForm(false);
      refetch();
    },
    onError: (error) => {
      toast.error(error.message || "Failed to create area");
    },
  });

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    if (!formData.name || !formData.displayName) {
      toast.error("Name and display name are required");
      return;
    }
    createMutation.mutate(formData);
  };

  return (
    <div className="space-y-6">
      {/* Form */}
      {showForm && (
        <Card className="p-6 border-slate-700 bg-slate-700/50">
          <h3 className="text-lg font-semibold text-white mb-4">Create New Area</h3>
          <form onSubmit={handleSubmit} className="space-y-4">
            <div>
              <label className="block text-sm font-medium text-slate-300 mb-2">
                Internal Name
              </label>
              <Input
                placeholder="e.g., loading-bay-a"
                value={formData.name}
                onChange={(e) => setFormData({ ...formData, name: e.target.value })}
                className="bg-slate-800 border-slate-600 text-white"
              />
            </div>
            <div>
              <label className="block text-sm font-medium text-slate-300 mb-2">
                Display Name
              </label>
              <Input
                placeholder="e.g., Loading Bay A"
                value={formData.displayName}
                onChange={(e) => setFormData({ ...formData, displayName: e.target.value })}
                className="bg-slate-800 border-slate-600 text-white"
              />
            </div>
            <div>
              <label className="block text-sm font-medium text-slate-300 mb-2">
                Description (Optional)
              </label>
              <Input
                placeholder="e.g., Main loading area for outbound shipments"
                value={formData.description}
                onChange={(e) => setFormData({ ...formData, description: e.target.value })}
                className="bg-slate-800 border-slate-600 text-white"
              />
            </div>
            <div className="flex gap-2">
              <Button
                type="submit"
                disabled={createMutation.isPending}
                className="bg-blue-600 hover:bg-blue-700"
              >
                {createMutation.isPending ? "Creating..." : "Create Area"}
              </Button>
              <Button
                type="button"
                variant="outline"
                onClick={() => setShowForm(false)}
                className="border-slate-600 text-slate-300 hover:bg-slate-700"
              >
                Cancel
              </Button>
            </div>
          </form>
        </Card>
      )}

      {/* Create Button */}
      {!showForm && (
        <Button
          onClick={() => setShowForm(true)}
          className="bg-blue-600 hover:bg-blue-700 gap-2"
        >
          <Plus className="w-4 h-4" />
          New Area
        </Button>
      )}

      {/* Areas List */}
      <div className="space-y-3">
        {isLoading ? (
          <div className="text-center py-8 text-slate-400">Loading areas...</div>
        ) : areas && areas.length > 0 ? (
          areas.map((area) => (
            <Card
              key={area.id}
              className="p-4 border-slate-700 bg-slate-700/30 hover:bg-slate-700/50 transition-colors"
            >
              <div className="flex items-center justify-between">
                <div className="flex-1">
                  <h4 className="font-semibold text-white">{area.displayName}</h4>
                  <p className="text-sm text-slate-400">{area.description || "No description"}</p>
                </div>
                <div className="flex gap-2">
                  <Button
                    size="sm"
                    variant="ghost"
                    onClick={() => setLocation(`/display/${area.id}`)}
                    className="text-slate-300 hover:text-white hover:bg-slate-600"
                  >
                    <Eye className="w-4 h-4" />
                  </Button>
                  <Button
                    size="sm"
                    variant="ghost"
                    className="text-slate-300 hover:text-white hover:bg-slate-600"
                  >
                    <Edit2 className="w-4 h-4" />
                  </Button>
                  <Button
                    size="sm"
                    variant="ghost"
                    className="text-red-400 hover:text-red-300 hover:bg-slate-600"
                  >
                    <Trash2 className="w-4 h-4" />
                  </Button>
                </div>
              </div>
            </Card>
          ))
        ) : (
          <div className="text-center py-8 text-slate-400">
            No areas created yet. Create one to get started.
          </div>
        )}
      </div>
    </div>
  );
}
