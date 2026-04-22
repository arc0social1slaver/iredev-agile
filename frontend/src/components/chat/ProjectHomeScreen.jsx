// src/components/chat/ProjectHomeScreen.jsx
// ─────────────────────────────────────────────────────────────────────────────
// Shown in the main chat area when the user selects a project from the sidebar
// (but hasn't opened a specific chat yet).
// Displays project info + list of past requirement processes + start new button.
// ─────────────────────────────────────────────────────────────────────────────
import { useState, useEffect } from "react";
import { Play, Clock, CheckCircle, Circle, Trash2, FolderOpen } from "lucide-react";
import { fetchProjectChats, deleteChat } from "../../services/chatService";
import { LoadingSpinner } from "../ui/LoadingSpinner";
import { ProcessConfigModal } from "../requirements/ProcessConfigModal";

function formatDate(iso) {
  if (!iso) return "";
  const d   = new Date(iso);
  const now = new Date();
  const diff = (now - d) / 1000;
  if (diff < 60)              return "just now";
  if (diff < 3600)            return `${Math.floor(diff / 60)}m ago`;
  if (diff < 86400)           return `${Math.floor(diff / 3600)}h ago`;
  if (diff < 86400 * 7)       return `${Math.floor(diff / 86400)}d ago`;
  return d.toLocaleDateString("en-US", { month: "short", day: "numeric" });
}

export function ProjectHomeScreen({ project, onOpenChat, onStartProcess }) {
  const [chats,       setChats]       = useState([]);
  const [loading,     setLoading]     = useState(true);
  const [showConfig,  setShowConfig]  = useState(false);

  useEffect(() => {
    if (!project?.id) return;
    setLoading(true);
    fetchProjectChats(project.id)
      .then(setChats)
      .catch(() => {})
      .finally(() => setLoading(false));
  }, [project?.id]);

  const handleDelete = async (e, chatId) => {
    e.stopPropagation();
    await deleteChat(chatId).catch(() => {});
    setChats((prev) => prev.filter((c) => c.id !== chatId));
  };

  const handleStart = async (config) => {
    setShowConfig(false);
    const chatId = await onStartProcess(config, project.id);
    // Refresh the list after starting
    fetchProjectChats(project.id).then(setChats).catch(() => {});
  };

  return (
    <div className="flex flex-col h-full overflow-y-auto bg-[#F4F0E6]">
      <div className="max-w-[680px] w-full mx-auto px-6 py-10">

        {/* Project header */}
        <div className="flex items-start gap-4 mb-8">
          <div className="w-12 h-12 rounded-2xl bg-[#C96A42]/10 border border-[#C96A42]/20
                          flex items-center justify-center flex-shrink-0">
            <FolderOpen size={22} className="text-[#C96A42]" />
          </div>
          <div>
            <h1 className="text-[22px] font-semibold text-[#1A1410] tracking-[-0.02em] leading-tight">
              {project.name}
            </h1>
            {project.description && (
              <p className="text-[13px] text-[#8A7F72] mt-1 leading-relaxed">
                {project.description}
              </p>
            )}
          </div>
        </div>

        {/* Start new process button — primary CTA */}
        <button
          onClick={() => setShowConfig(true)}
          className="w-full flex items-center gap-3 px-5 py-4 mb-8
                     bg-white border-2 border-dashed border-[#E2DCCF]
                     hover:border-[#C96A42] hover:bg-[#FDF8F5]
                     rounded-2xl transition-all duration-150 group text-left"
        >
          <div className="w-9 h-9 rounded-xl bg-[#C96A42]/10 group-hover:bg-[#C96A42]/15
                          flex items-center justify-center flex-shrink-0 transition-colors">
            <Play size={16} className="text-[#C96A42]" />
          </div>
          <div>
            <div className="text-[14px] font-semibold text-[#1A1410]">
              Start new requirements process
            </div>
            <div className="text-[12px] text-[#8A7F72] mt-0.5">
              Run AI-guided stakeholder interview and backlog generation
            </div>
          </div>
        </button>

        {/* Past processes */}
        <div>
          <div className="text-[11px] font-semibold text-[#A89F97] uppercase tracking-wider mb-3">
            Requirement Processes
          </div>

          {loading ? (
            <div className="flex items-center justify-center py-12">
              <LoadingSpinner size={20} className="text-[#C96A42]" />
            </div>
          ) : chats.length === 0 ? (
            <div className="text-center py-12">
              <div className="text-[#C0B8AE] text-[13px]">No processes yet</div>
              <div className="text-[#C0B8AE] text-[12px] mt-1">
                Start your first requirements process above
              </div>
            </div>
          ) : (
            <div className="space-y-2">
              {chats.map((chat, idx) => (
                <div
                  key={chat.id}
                  onClick={() => onOpenChat(chat.id, project.id)}
                  className="flex items-center gap-4 px-4 py-3.5
                             bg-white border border-[#E8E3D9] rounded-xl
                             hover:border-[#D9D3C8] hover:bg-[#FAF8F4]
                             hover:shadow-[0_2px_8px_rgba(0,0,0,0.05)]
                             cursor-pointer transition-all duration-150 group"
                >
                  {/* Index circle */}
                  <div className="w-8 h-8 rounded-full bg-[#EAE6DC] flex items-center
                                  justify-center flex-shrink-0 text-[12px] font-semibold
                                  text-[#8A7F72] group-hover:bg-[#E2DCCF]">
                    {chats.length - idx}
                  </div>

                  {/* Title + date */}
                  <div className="flex-1 min-w-0">
                    <div className="text-[13.5px] font-medium text-[#1A1410] truncate leading-snug">
                      {chat.title}
                    </div>
                    <div className="flex items-center gap-1.5 mt-0.5">
                      <Clock size={10} className="text-[#C0B8AE] flex-shrink-0" />
                      <span className="text-[11px] text-[#B5ADA4]">
                        {formatDate(chat.createdAt)}
                      </span>
                    </div>
                  </div>

                  {/* Delete button */}
                  <button
                    onClick={(e) => handleDelete(e, chat.id)}
                    className="opacity-0 group-hover:opacity-100 p-1.5 rounded-lg
                               text-[#C0B8AE] hover:text-red-400 hover:bg-red-50
                               transition-all flex-shrink-0"
                  >
                    <Trash2 size={13} />
                  </button>
                </div>
              ))}
            </div>
          )}
        </div>
      </div>

      {/* Process config modal */}
      <ProcessConfigModal
        open={showConfig}
        onClose={() => setShowConfig(false)}
        onStart={handleStart}
      />
    </div>
  );
}