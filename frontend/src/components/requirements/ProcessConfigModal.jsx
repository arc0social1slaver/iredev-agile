import { useState } from "react";
import { Modal } from "../ui";
import { ChevronDown, ChevronUp } from "lucide-react";

export function ProcessConfigModal({ open, onClose, onStart }) {
  const [config, setConfig] = useState({
    projectName: "",
    projectDescription: "",
    maxIterations: 20,
  });

  const [expandedSections, setExpandedSections] = useState({
    basic: true,
    stakeholders: true,
    advanced: false,
  });

  const toggleSection = (section) => {
    setExpandedSections((prev) => ({
      ...prev,
      [section]: !prev[section],
    }));
  };

  const handleSubmit = (e) => {
    e.preventDefault();
    onStart(config);
    onClose();
    setConfig({
      projectName: "",
      projectDescription: "",
      maxIterations: 20,
    });
  };

  return (
    <Modal
      open={open}
      onClose={onClose}
      title="Requirements Process Configuration"
      width="max-w-[520px]"
    >
      <form onSubmit={handleSubmit} className="flex-1 overflow-y-auto p-4">
        {/* Basic Section */}
        <div className="mb-4 border rounded-lg">
          <button
            type="button"
            onClick={() => toggleSection("basic")}
            className="w-full flex items-center justify-between p-3 hover:bg-gray-50"
          >
            <span className="font-medium">Basic Configuration</span>
            {expandedSections.basic ? (
              <ChevronUp className="w-4 h-4" />
            ) : (
              <ChevronDown className="w-4 h-4" />
            )}
          </button>

          {expandedSections.basic && (
            <div className="p-3 pt-0 space-y-3">
              <div>
                <label className="block text-sm font-medium mb-1">
                  Project Name *
                </label>
                <input
                  type="text"
                  value={config.projectName}
                  onChange={(e) =>
                    setConfig({ ...config, projectName: e.target.value })
                  }
                  className="w-full px-3 py-2 border rounded-lg focus:ring-2 focus:ring-[#C96A42] focus:outline-none"
                  placeholder="Enter project name"
                  required
                />
              </div>

              <div>
                <label className="block text-sm font-medium mb-1">
                  Project Description *
                </label>
                <textarea
                  value={config.projectDescription}
                  onChange={(e) =>
                    setConfig({ ...config, projectDescription: e.target.value })
                  }
                  className="w-full px-3 py-2 border rounded-lg focus:ring-2 focus:ring-[#C96A42] focus:outline-none"
                  placeholder="Enter project description"
                  required
                  style={{
                    fieldSizing: "content",
                  }}
                />
              </div>

              <div>
                <label className="block text-sm font-medium mb-1">
                  Max Iterations
                </label>
                <input
                  type="number"
                  min="1"
                  max="5"
                  value={config.maxIterations}
                  onChange={(e) =>
                    setConfig({
                      ...config,
                      maxIterations: parseInt(e.target.value),
                    })
                  }
                  className="w-full px-3 py-2 border rounded-lg"
                />
              </div>
            </div>
          )}
        </div>
      </form>

      <div className="flex justify-end gap-3 p-4 border-t">
        <button
          onClick={onClose}
          className="px-4 py-2 border rounded-lg hover:bg-gray-50"
        >
          Cancel
        </button>
        <button
          onClick={handleSubmit}
          className="px-4 py-2 bg-[#C96A42] text-white rounded-lg hover:bg-[#B85A32]"
        >
          Start Process
        </button>
      </div>
    </Modal>
  );
}
