import { useState } from "react";
import { Modal } from "../ui";
import { ChevronDown, ChevronUp } from "lucide-react";

export function ProcessConfigModal({ open, onClose, onStart }) {
  const [config, setConfig] = useState({
    projectName: "",
    domain: "software",
    stakeholders: ["CEO", "CTO", "Product Manager"],
    targetEnvironment: "cloud",
    complianceRequirements: [],
    qualityStandards: ["ISO 25010"],
    timeoutMinutes: 1440,
    maxIterations: 3,
    customConfig: {
      methodology: "5w1h",
      maxQuestionsPerStakeholder: 7,
      completenessThreshold: 0.8,
    },
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
                <label className="block text-sm font-medium mb-1">Domain</label>
                <select
                  value={config.domain}
                  onChange={(e) =>
                    setConfig({ ...config, domain: e.target.value })
                  }
                  className="w-full px-3 py-2 border rounded-lg focus:ring-2 focus:ring-[#C96A42] focus:outline-none"
                >
                  <option value="software">Software Development</option>
                  <option value="healthcare">Healthcare</option>
                  <option value="finance">Finance</option>
                  <option value="ecommerce">E-Commerce</option>
                  <option value="education">Education</option>
                  <option value="manufacturing">Manufacturing</option>
                </select>
              </div>

              <div>
                <label className="block text-sm font-medium mb-1">
                  Target Environment
                </label>
                <select
                  value={config.targetEnvironment}
                  onChange={(e) =>
                    setConfig({ ...config, targetEnvironment: e.target.value })
                  }
                  className="w-full px-3 py-2 border rounded-lg focus:ring-2 focus:ring-[#C96A42] focus:outline-none"
                >
                  <option value="cloud">Cloud</option>
                  <option value="onpremise">On-Premise</option>
                  <option value="hybrid">Hybrid</option>
                  <option value="mobile">Mobile</option>
                  <option value="embedded">Embedded</option>
                </select>
              </div>
            </div>
          )}
        </div>

        {/* Stakeholders Section */}
        <div className="mb-4 border rounded-lg">
          <button
            type="button"
            onClick={() => toggleSection("stakeholders")}
            className="w-full flex items-center justify-between p-3 hover:bg-gray-50"
          >
            <span className="font-medium">Stakeholders</span>
            {expandedSections.stakeholders ? (
              <ChevronUp className="w-4 h-4" />
            ) : (
              <ChevronDown className="w-4 h-4" />
            )}
          </button>

          {expandedSections.stakeholders && (
            <div className="p-3 pt-0">
              <div className="flex flex-wrap gap-2 mb-3">
                {config.stakeholders.map((stakeholder, idx) => (
                  <span
                    key={idx}
                    className="px-2 py-1 bg-gray-100 rounded-full text-sm"
                  >
                    {stakeholder}
                    <button
                      type="button"
                      onClick={() => {
                        const newStakeholders = config.stakeholders.filter(
                          (_, i) => i !== idx,
                        );
                        setConfig({ ...config, stakeholders: newStakeholders });
                      }}
                      className="ml-2 text-gray-500 hover:text-red-500"
                    >
                      ×
                    </button>
                  </span>
                ))}
              </div>

              <div className="flex gap-2">
                <input
                  type="text"
                  id="newStakeholder"
                  placeholder="Add stakeholder..."
                  className="flex-1 px-3 py-2 border rounded-lg focus:ring-2 focus:ring-[#C96A42] focus:outline-none"
                  onKeyDown={(e) => {
                    if (e.key === "Enter") {
                      const input = e.target;
                      const value = input.value.trim();
                      if (value && !config.stakeholders.includes(value)) {
                        setConfig({
                          ...config,
                          stakeholders: [...config.stakeholders, value],
                        });
                        input.value = "";
                      }
                    }
                  }}
                />
                <button
                  type="button"
                  onClick={() => {
                    const input = document.getElementById("newStakeholder");
                    const value = input.value.trim();
                    if (value && !config.stakeholders.includes(value)) {
                      setConfig({
                        ...config,
                        stakeholders: [...config.stakeholders, value],
                      });
                      input.value = "";
                    }
                  }}
                  className="px-3 py-2 bg-gray-100 rounded-lg hover:bg-gray-200"
                >
                  Add
                </button>
              </div>
            </div>
          )}
        </div>

        {/* Advanced Section */}
        <div className="mb-4 border rounded-lg">
          <button
            type="button"
            onClick={() => toggleSection("advanced")}
            className="w-full flex items-center justify-between p-3 hover:bg-gray-50"
          >
            <span className="font-medium">Advanced Configuration</span>
            {expandedSections.advanced ? (
              <ChevronUp className="w-4 h-4" />
            ) : (
              <ChevronDown className="w-4 h-4" />
            )}
          </button>

          {expandedSections.advanced && (
            <div className="p-3 pt-0 space-y-3">
              <div>
                <label className="block text-sm font-medium mb-1">
                  Methodology
                </label>
                <select
                  value={config.customConfig.methodology}
                  onChange={(e) =>
                    setConfig({
                      ...config,
                      customConfig: {
                        ...config.customConfig,
                        methodology: e.target.value,
                      },
                    })
                  }
                  className="w-full px-3 py-2 border rounded-lg"
                >
                  <option value="5w1h">5W1H Framework</option>
                  <option value="socratic">Socratic Questioning</option>
                </select>
              </div>

              <div>
                <label className="block text-sm font-medium mb-1">
                  Max Questions Per Stakeholder
                </label>
                <input
                  type="number"
                  min="3"
                  max="15"
                  value={config.customConfig.maxQuestionsPerStakeholder}
                  onChange={(e) =>
                    setConfig({
                      ...config,
                      customConfig: {
                        ...config.customConfig,
                        maxQuestionsPerStakeholder: parseInt(e.target.value),
                      },
                    })
                  }
                  className="w-full px-3 py-2 border rounded-lg"
                />
              </div>

              <div>
                <label className="block text-sm font-medium mb-1">
                  Completeness Threshold
                </label>
                <input
                  type="range"
                  min="0"
                  max="1"
                  step="0.05"
                  value={config.customConfig.completenessThreshold}
                  onChange={(e) =>
                    setConfig({
                      ...config,
                      customConfig: {
                        ...config.customConfig,
                        completenessThreshold: parseFloat(e.target.value),
                      },
                    })
                  }
                  className="w-full"
                />
                <div className="text-sm text-gray-500 mt-1">
                  {Math.round(config.customConfig.completenessThreshold * 100)}%
                </div>
              </div>

              <div>
                <label className="block text-sm font-medium mb-1">
                  Timeout (minutes)
                </label>
                <input
                  type="number"
                  min="30"
                  max="4320"
                  value={config.timeoutMinutes}
                  onChange={(e) =>
                    setConfig({
                      ...config,
                      timeoutMinutes: parseInt(e.target.value),
                    })
                  }
                  className="w-full px-3 py-2 border rounded-lg"
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
