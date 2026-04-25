/**
 * RAKSHA-FORCE — Shared Frontend Utilities
 */

const Utils = {
  /** Format a date string into a human-readable format */
  formatDate: (dateStr) => {
    if (!dateStr) return '—';
    const date = new Date(dateStr);
    return date.toLocaleString('en-IN', {
      day: '2-digit',
      month: 'short',
      year: 'numeric',
      hour: '2-digit',
      minute: '2-digit',
      hour12: true
    });
  },

  /** Get time ago string */
  timeAgo: (dateStr) => {
    if (!dateStr) return '—';
    const seconds = Math.floor((new Date() - new Date(dateStr)) / 1000);
    let interval = seconds / 31536000;
    if (interval > 1) return Math.floor(interval) + "y ago";
    interval = seconds / 2592000;
    if (interval > 1) return Math.floor(interval) + "mo ago";
    interval = seconds / 86400;
    if (interval > 1) return Math.floor(interval) + "d ago";
    interval = seconds / 3600;
    if (interval > 1) return Math.floor(interval) + "h ago";
    interval = seconds / 60;
    if (interval > 1) return Math.floor(interval) + "m ago";
    return Math.floor(seconds) + "s ago";
  },

  /** Show a toast notification */
  showNotif: (msg, isError = false) => {
    const container = document.getElementById('toastContainer') || document.body;
    const toast = document.createElement('div');
    toast.className = `toast ${isError ? 'toast-error' : 'toast-success'}`;
    toast.style.cssText = `
      position: fixed;
      bottom: 24px;
      right: 24px;
      background: ${isError ? 'var(--red)' : 'var(--blue)'};
      color: white;
      padding: 12px 24px;
      border-radius: 2px;
      font-family: 'Orbitron', monospace;
      font-size: 11px;
      letter-spacing: 1px;
      box-shadow: 0 8px 32px rgba(0,0,0,0.5);
      z-index: 10000;
      animation: toastIn 0.3s ease-out;
      display: flex;
      align-items: center;
      gap: 12px;
    `;
    toast.innerHTML = `<span>${isError ? '⚠️' : '✅'}</span> ${msg}`;
    container.appendChild(toast);
    setTimeout(() => {
      toast.style.animation = 'toastOut 0.3s ease-in forwards';
      setTimeout(() => toast.remove(), 300);
    }, 4000);
  },

  /** Inject Toast Animations */
  injectAnimations: () => {
    if (document.getElementById('utils-animations')) return;
    const style = document.createElement('style');
    style.id = 'utils-animations';
    style.textContent = `
      @keyframes toastIn { from { opacity: 0; transform: translateY(20px); } to { opacity: 1; transform: translateY(0); } }
      @keyframes toastOut { from { opacity: 1; transform: translateY(0); } to { opacity: 0; transform: translateY(20px); } }
    `;
    document.head.appendChild(style);
  }
};

Utils.injectAnimations();
window.Utils = Utils;
