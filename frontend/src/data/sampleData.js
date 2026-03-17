// src/data/sampleData.js
// ─────────────────────────────────────────────────────────────────────────────
// Static seed data used to pre-populate the UI on first load.
// In a real app this data would come from an API.
// ─────────────────────────────────────────────────────────────────────────────

/**
 * The source code for the dashboard artifact in the first sample chat.
 * Kept as a separate variable so SAMPLE_CHATS stays easy to read.
 */
const DASHBOARD_CODE = `// Runs inside the sandboxed artifact preview iframe

function StatCard({ title, value, change }) {
  return (
    <div style={{background:'#fff',borderRadius:12,padding:'20px 24px',
                 boxShadow:'0 1px 4px rgba(0,0,0,0.08)',flex:1}}>
      <div style={{fontSize:13,color:'#888',marginBottom:6}}>{title}</div>
      <div style={{fontSize:28,fontWeight:700,color:'#1a1a1a'}}>{value}</div>
      {change !== undefined && (
        <div style={{fontSize:12,color:change>0?'#22c55e':'#ef4444',marginTop:4}}>
          {change > 0 ? '▲' : '▼'} {Math.abs(change)}% vs last month
        </div>
      )}
    </div>
  )
}

export default function Dashboard() {
  const stats = [
    { title:'Total Users',   value:'1,240', change:  12 },
    { title:'Revenue',       value:'$8,320',change: 5.4 },
    { title:'Active Orders', value:'340',   change:-2.1 },
    { title:'Avg. Session',  value:'4m 12s',change:   8 },
  ]
  const activity = [
    'Alice signed up',
    'Bob placed order #1042',
    'Carol upgraded plan',
    'Dave cancelled subscription',
  ]
  return (
    <div style={{padding:32,background:'#f8f9fb',minHeight:'100vh',fontFamily:'system-ui'}}>
      <h1 style={{fontSize:22,fontWeight:700,marginBottom:24,color:'#1a1a1a'}}>
        📊 My Dashboard
      </h1>
      <div style={{display:'flex',gap:16,marginBottom:32,flexWrap:'wrap'}}>
        {stats.map(s => <StatCard key={s.title} {...s} />)}
      </div>
      <div style={{background:'#fff',borderRadius:12,padding:24,
                   boxShadow:'0 1px 4px rgba(0,0,0,0.08)'}}>
        <div style={{fontSize:14,fontWeight:600,marginBottom:16,color:'#1a1a1a'}}>
          Recent Activity
        </div>
        {activity.map((item, i) => (
          <div key={i} style={{display:'flex',alignItems:'center',gap:12,
                               padding:'10px 0',borderBottom:'1px solid #f0f0f0'}}>
            <div style={{width:8,height:8,borderRadius:'50%',
                         background:['#6366f1','#22c55e','#f59e0b','#ef4444'][i]}} />
            <span style={{fontSize:14,color:'#444'}}>{item}</span>
            <span style={{marginLeft:'auto',fontSize:12,color:'#aaa'}}>{i+1}h ago</span>
          </div>
        ))}
      </div>
    </div>
  )
}`

/**
 * Pre-loaded conversations shown in the sidebar.
 * shape: { id, title, date, messages: [{ id, role, content, artifact? }] }
 */
export const SAMPLE_CHATS = [
  {
    id: 'c1',
    title: 'Build a React dashboard',
    date: 'Today',
    messages: [
      {
        id: 'm1',
        role: 'user',
        content: 'Can you build me a simple dashboard in React?',
      },
      {
        id: 'm2',
        role: 'assistant',
        content:
          "Sure! Here's a clean dashboard layout:\n\n```jsx\n// Dashboard.jsx\nexport function Dashboard() {\n  return (\n    <div className=\"grid grid-cols-3 gap-4 p-6\">\n      <StatCard title=\"Users\"   value=\"1,240\" />\n      <StatCard title=\"Revenue\" value=\"$8,320\" />\n      <StatCard title=\"Orders\"  value=\"340\" />\n    </div>\n  )\n}\n```\n\nEach **StatCard** receives a `title` and `value` prop. Want me to add charts too?",
        // Presence of `artifact` causes a preview card to appear under the message
        artifact: {
          id: 'a1',
          type: 'react',
          title: 'Dashboard Component',
          language: 'jsx',
          content: DASHBOARD_CODE,
        },
      },
    ],
  },
  {
    id: 'c2',
    title: 'Explain async/await in JS',
    date: 'Today',
    messages: [
      { id: 'm3', role: 'user', content: 'Explain async/await in JavaScript simply.' },
      {
        id: 'm4',
        role: 'assistant',
        content:
          '**async/await** makes asynchronous code look synchronous.\n\n- `async` marks a function as asynchronous — it always returns a **Promise**\n- `await` pauses execution inside that function until a Promise resolves\n\n```javascript\n// Without async/await (Promise chains)\nfetch("/api/user")\n  .then(res => res.json())\n  .then(user => console.log(user))\n\n// With async/await (much cleaner!)\nasync function getUser() {\n  const res  = await fetch("/api/user")\n  const user = await res.json()\n  console.log(user)\n}\n```\n\nThink of `await` as saying **"wait here until this is done, then continue."**',
      },
    ],
  },
  { id: 'c3', title: 'Python pandas cheatsheet',       date: 'Yesterday', messages: [] },
  { id: 'c4', title: 'Travel itinerary Tokyo',          date: 'Yesterday', messages: [] },
  { id: 'c5', title: 'Marketing email for SaaS launch', date: 'Mar 12',    messages: [] },
]

/**
 * Quick-start chips shown on the welcome / home screen.
 */
export const STARTER_PROMPTS = [
  { id: 'p1', icon: '✍️', label: 'Write',      text: 'Help me write a professional cover letter' },
  { id: 'p2', icon: '💻', label: 'Code',       text: 'Build a responsive navbar in React + Tailwind' },
  { id: 'p3', icon: '🔍', label: 'Analyze',    text: 'Analyze this dataset and find key insights' },
  { id: 'p4', icon: '💡', label: 'Brainstorm', text: 'Give me 10 startup ideas in the EdTech space' },
]