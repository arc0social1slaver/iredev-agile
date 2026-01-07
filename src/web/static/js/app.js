/**
 * iReDev Framework Web Interface JavaScript
 * Handles real-time updates, UI interactions, and WebSocket communication
 */

class iReDevApp {
    constructor() {
        this.socket = null;
        this.currentSessionId = null;
        this.notifications = [];
        this.init();
    }

    init() {
        this.initializeSocket();
        this.setupEventListeners();
        this.initializeComponents();
        console.log('iReDev Web Interface initialized');
    }

    initializeSocket() {
        if (typeof io !== 'undefined') {
            this.socket = io();
            this.setupSocketEvents();
        }
    }

    setupSocketEvents() {
        if (!this.socket) return;

        this.socket.on('connect', () => {
            console.log('Connected to iReDev server');
            this.showNotification('Connected to server', 'success', 3000);
        });

        this.socket.on('disconnect', () => {
            console.log('Disconnected from iReDev server');
            this.showNotification('Disconnected from server', 'warning', 5000);
        });

        this.socket.on('phase_started', (data) => {
            console.log('Phase started:', data);
            this.handlePhaseStarted(data);
        });

        this.socket.on('phase_completed', (data) => {
            console.log('Phase completed:', data);
            this.handlePhaseCompleted(data);
        });

        this.socket.on('review_required', (data) => {
            console.log('Review required:', data);
            this.handleReviewRequired(data);
        });

        this.socket.on('artifact_created', (data) => {
            console.log('Artifact created:', data);
            this.handleArtifactCreated(data);
        });

        this.socket.on('artifact_updated', (data) => {
            console.log('Artifact updated:', data);
            this.handleArtifactUpdated(data);
        });
    }

    setupEventListeners() {
        // Auto-refresh functionality
        this.setupAutoRefresh();
        
        // Form enhancements
        this.setupFormEnhancements();
        
        // Table interactions
        this.setupTableInteractions();
        
        // Modal interactions
        this.setupModalInteractions();
        
        // Keyboard shortcuts
        this.setupKeyboardShortcuts();
    }

    initializeComponents() {
        // Initialize tooltips
        this.initializeTooltips();
        
        // Initialize progress bars
        this.initializeProgressBars();
        
        // Initialize countdown timers
        this.initializeCountdowns();
        
        // Initialize charts (if needed)
        this.initializeCharts();
    }

    // Socket Event Handlers
    handlePhaseStarted(data) {
        this.showNotification(
            `Phase started: ${this.formatPhase(data.phase)}`,
            'info',
            5000
        );
        
        if (data.session_id === this.currentSessionId) {
            this.updateProcessStatus(data);
        }
        
        this.updateDashboardStats();
    }

    handlePhaseCompleted(data) {
        this.showNotification(
            `Phase completed: ${this.formatPhase(data.phase)}`,
            'success',
            5000
        );
        
        if (data.session_id === this.currentSessionId) {
            this.updateProcessStatus(data);
        }
        
        this.updateDashboardStats();
    }

    handleReviewRequired(data) {
        this.showNotification(
            'New review required',
            'warning',
            0, // Don't auto-dismiss
            {
                action: 'View Review',
                url: `/review/${data.review_id || ''}`
            }
        );
        
        this.updateReviewCount();
    }

    handleArtifactCreated(data) {
        this.showNotification(
            `New artifact created: ${this.formatArtifactType(data.artifact_type)}`,
            'info',
            4000
        );
        
        if (data.session_id === this.currentSessionId) {
            this.updateArtifactsList(data);
        }
    }

    handleArtifactUpdated(data) {
        if (data.session_id === this.currentSessionId) {
            this.updateArtifactsList(data);
        }
    }

    // UI Update Methods
    updateProcessStatus(data) {
        // Update progress bar
        const progressBar = document.querySelector('.progress-bar');
        if (progressBar && data.progress !== undefined) {
            const percentage = Math.round(data.progress * 100);
            progressBar.style.width = `${percentage}%`;
            progressBar.setAttribute('aria-valuenow', percentage);
            progressBar.textContent = `${percentage}%`;
        }

        // Update phase indicator
        const phaseElement = document.querySelector('.current-phase');
        if (phaseElement && data.phase) {
            phaseElement.textContent = this.formatPhase(data.phase);
        }

        // Update timeline if present
        this.updateTimeline(data.phase);
    }

    updateTimeline(currentPhase) {
        const timelineItems = document.querySelectorAll('.timeline-item');
        const phases = [
            'initialization', 'interview', 'user_modeling', 'deployment_analysis',
            'requirement_analysis', 'url_review', 'requirement_modeling',
            'model_review', 'srs_generation', 'srs_review', 'quality_assurance', 'completed'
        ];

        const currentIndex = phases.indexOf(currentPhase);
        
        timelineItems.forEach((item, index) => {
            const marker = item.querySelector('.timeline-marker');
            if (!marker) return;

            item.classList.remove('completed', 'current', 'pending');
            
            if (index < currentIndex) {
                item.classList.add('completed');
                marker.classList.remove('bg-primary', 'bg-light');
                marker.classList.add('bg-success');
            } else if (index === currentIndex) {
                item.classList.add('current');
                marker.classList.remove('bg-success', 'bg-light');
                marker.classList.add('bg-primary');
            } else {
                item.classList.add('pending');
                marker.classList.remove('bg-success', 'bg-primary');
                marker.classList.add('bg-light');
            }
        });
    }

    updateDashboardStats() {
        // Refresh dashboard statistics
        if (window.location.pathname === '/') {
            setTimeout(() => {
                this.refreshDashboardData();
            }, 2000);
        }
    }

    updateReviewCount() {
        // Update review count in navigation or dashboard
        const reviewCountElements = document.querySelectorAll('.review-count');
        reviewCountElements.forEach(element => {
            const currentCount = parseInt(element.textContent) || 0;
            element.textContent = currentCount + 1;
        });
    }

    updateArtifactsList(data) {
        // Update artifacts list if on process detail page
        const artifactsList = document.querySelector('.artifacts-list');
        if (artifactsList) {
            // Add new artifact or update existing one
            this.refreshArtifactsList();
        }
    }

    // Notification System
    showNotification(message, type = 'info', duration = 5000, action = null) {
        const notification = this.createNotificationElement(message, type, action);
        this.displayNotification(notification);
        
        if (duration > 0) {
            setTimeout(() => {
                this.removeNotification(notification);
            }, duration);
        }
        
        this.notifications.push({
            element: notification,
            timestamp: Date.now(),
            type: type,
            message: message
        });
    }

    createNotificationElement(message, type, action) {
        const alertClass = this.getAlertClass(type);
        const iconClass = this.getIconClass(type);
        
        const notification = document.createElement('div');
        notification.className = `alert ${alertClass} alert-dismissible fade show notification-toast`;
        notification.style.cssText = `
            position: fixed;
            top: 20px;
            right: 20px;
            z-index: 1050;
            min-width: 300px;
            max-width: 500px;
            box-shadow: 0 0.5rem 1rem rgba(0, 0, 0, 0.15);
        `;
        
        let actionHtml = '';
        if (action) {
            actionHtml = `
                <a href="${action.url}" class="btn btn-sm btn-outline-${type === 'warning' ? 'dark' : 'light'} ms-2">
                    ${action.action}
                </a>
            `;
        }
        
        notification.innerHTML = `
            <i class="${iconClass} me-2"></i>
            ${message}
            ${actionHtml}
            <button type="button" class="btn-close" data-bs-dismiss="alert"></button>
        `;
        
        return notification;
    }

    displayNotification(notification) {
        document.body.appendChild(notification);
        
        // Animate in
        setTimeout(() => {
            notification.classList.add('show');
        }, 10);
    }

    removeNotification(notification) {
        if (notification && notification.parentNode) {
            notification.classList.remove('show');
            setTimeout(() => {
                if (notification.parentNode) {
                    notification.parentNode.removeChild(notification);
                }
            }, 150);
        }
    }

    // Utility Methods
    formatPhase(phase) {
        return phase.replace(/_/g, ' ').replace(/\b\w/g, l => l.toUpperCase());
    }

    formatArtifactType(type) {
        return type.replace(/_/g, ' ').replace(/\b\w/g, l => l.toUpperCase());
    }

    getAlertClass(type) {
        const classMap = {
            'success': 'alert-success',
            'error': 'alert-danger',
            'warning': 'alert-warning',
            'info': 'alert-info'
        };
        return classMap[type] || 'alert-info';
    }

    getIconClass(type) {
        const iconMap = {
            'success': 'fas fa-check-circle',
            'error': 'fas fa-exclamation-circle',
            'warning': 'fas fa-exclamation-triangle',
            'info': 'fas fa-info-circle'
        };
        return iconMap[type] || 'fas fa-info-circle';
    }

    // Component Initialization
    initializeTooltips() {
        if (typeof bootstrap !== 'undefined') {
            const tooltipTriggerList = [].slice.call(document.querySelectorAll('[data-bs-toggle="tooltip"]'));
            tooltipTriggerList.map(tooltipTriggerEl => new bootstrap.Tooltip(tooltipTriggerEl));
        }
    }

    initializeProgressBars() {
        const progressBars = document.querySelectorAll('.progress-bar');
        progressBars.forEach(bar => {
            const width = bar.style.width;
            bar.style.width = '0%';
            setTimeout(() => {
                bar.style.width = width;
            }, 100);
        });
    }

    initializeCountdowns() {
        const countdownElements = document.querySelectorAll('[data-countdown]');
        countdownElements.forEach(element => {
            const targetDate = new Date(element.dataset.countdown);
            this.startCountdown(element, targetDate);
        });
    }

    initializeCharts() {
        // Initialize any charts if Chart.js is available
        if (typeof Chart !== 'undefined') {
            this.initializeDashboardCharts();
        }
    }

    // Enhanced Functionality
    setupAutoRefresh() {
        // Auto-refresh for dashboard and monitoring pages
        if (window.location.pathname === '/' || window.location.pathname.includes('/monitor')) {
            setInterval(() => {
                this.refreshPageData();
            }, 30000); // Refresh every 30 seconds
        }
    }

    setupFormEnhancements() {
        // Auto-resize textareas
        const textareas = document.querySelectorAll('textarea');
        textareas.forEach(textarea => {
            textarea.addEventListener('input', () => {
                this.autoResizeTextarea(textarea);
            });
        });

        // Form validation enhancements
        const forms = document.querySelectorAll('form');
        forms.forEach(form => {
            form.addEventListener('submit', (e) => {
                if (!this.validateForm(form)) {
                    e.preventDefault();
                }
            });
        });
    }

    setupTableInteractions() {
        // Enhanced table interactions
        const tables = document.querySelectorAll('.table');
        tables.forEach(table => {
            // Add sorting if not already present
            this.addTableSorting(table);
            
            // Add row selection
            this.addRowSelection(table);
        });
    }

    setupModalInteractions() {
        // Enhanced modal interactions
        const modals = document.querySelectorAll('.modal');
        modals.forEach(modal => {
            modal.addEventListener('shown.bs.modal', () => {
                const firstInput = modal.querySelector('input, textarea, select');
                if (firstInput) {
                    firstInput.focus();
                }
            });
        });
    }

    setupKeyboardShortcuts() {
        document.addEventListener('keydown', (e) => {
            // Ctrl/Cmd + K for search
            if ((e.ctrlKey || e.metaKey) && e.key === 'k') {
                e.preventDefault();
                const searchInput = document.querySelector('#search-input');
                if (searchInput) {
                    searchInput.focus();
                }
            }
            
            // Escape to close modals/notifications
            if (e.key === 'Escape') {
                const openModal = document.querySelector('.modal.show');
                if (openModal) {
                    const modal = bootstrap.Modal.getInstance(openModal);
                    if (modal) {
                        modal.hide();
                    }
                }
                
                // Close notifications
                const notifications = document.querySelectorAll('.notification-toast');
                notifications.forEach(notification => {
                    this.removeNotification(notification);
                });
            }
        });
    }

    // Helper Methods
    autoResizeTextarea(textarea) {
        textarea.style.height = 'auto';
        textarea.style.height = textarea.scrollHeight + 'px';
    }

    validateForm(form) {
        const requiredFields = form.querySelectorAll('[required]');
        let isValid = true;
        
        requiredFields.forEach(field => {
            if (!field.value.trim()) {
                field.classList.add('is-invalid');
                isValid = false;
            } else {
                field.classList.remove('is-invalid');
            }
        });
        
        return isValid;
    }

    addTableSorting(table) {
        const headers = table.querySelectorAll('th');
        headers.forEach((header, index) => {
            if (!header.classList.contains('no-sort')) {
                header.style.cursor = 'pointer';
                header.addEventListener('click', () => {
                    this.sortTable(table, index);
                });
            }
        });
    }

    addRowSelection(table) {
        const rows = table.querySelectorAll('tbody tr');
        rows.forEach(row => {
            row.addEventListener('click', (e) => {
                if (e.target.tagName !== 'A' && e.target.tagName !== 'BUTTON') {
                    row.classList.toggle('table-active');
                }
            });
        });
    }

    sortTable(table, columnIndex) {
        const tbody = table.querySelector('tbody');
        const rows = Array.from(tbody.querySelectorAll('tr'));
        
        const isAscending = !table.dataset.sortAsc || table.dataset.sortAsc === 'false';
        table.dataset.sortAsc = isAscending;
        
        rows.sort((a, b) => {
            const aText = a.cells[columnIndex].textContent.trim();
            const bText = b.cells[columnIndex].textContent.trim();
            
            const aNum = parseFloat(aText);
            const bNum = parseFloat(bText);
            
            if (!isNaN(aNum) && !isNaN(bNum)) {
                return isAscending ? aNum - bNum : bNum - aNum;
            }
            
            return isAscending ? aText.localeCompare(bText) : bText.localeCompare(aText);
        });
        
        rows.forEach(row => tbody.appendChild(row));
    }

    startCountdown(element, targetDate) {
        const updateCountdown = () => {
            const now = new Date();
            const diff = targetDate - now;
            
            if (diff <= 0) {
                element.innerHTML = '<span class="text-danger">EXPIRED</span>';
                return;
            }
            
            const hours = Math.floor(diff / (1000 * 60 * 60));
            const minutes = Math.floor((diff % (1000 * 60 * 60)) / (1000 * 60));
            const seconds = Math.floor((diff % (1000 * 60)) / 1000);
            
            element.innerHTML = `${hours}h ${minutes}m ${seconds}s`;
        };
        
        updateCountdown();
        setInterval(updateCountdown, 1000);
    }

    refreshPageData() {
        // Refresh page data without full reload
        if (window.location.pathname === '/') {
            this.refreshDashboardData();
        }
    }

    refreshDashboardData() {
        fetch('/api/sessions')
            .then(response => response.json())
            .then(data => {
                this.updateDashboardSessions(data);
            })
            .catch(error => {
                console.error('Error refreshing dashboard data:', error);
            });
    }

    refreshArtifactsList() {
        if (this.currentSessionId) {
            // Refresh artifacts list for current session
            // This would need to be implemented based on API endpoints
        }
    }

    updateDashboardSessions(sessions) {
        // Update session cards on dashboard
        const sessionContainer = document.querySelector('.sessions-container');
        if (sessionContainer) {
            // Update session data
            // This would need more detailed implementation
        }
    }

    // Session Management
    joinSession(sessionId) {
        if (this.socket && sessionId) {
            this.currentSessionId = sessionId;
            this.socket.emit('join_session', { session_id: sessionId });
        }
    }

    leaveSession() {
        if (this.socket && this.currentSessionId) {
            this.socket.emit('leave_session', { session_id: this.currentSessionId });
            this.currentSessionId = null;
        }
    }
}

// Initialize the application when DOM is loaded
document.addEventListener('DOMContentLoaded', () => {
    window.iReDevApp = new iReDevApp();
    
    // Auto-join session if on process detail page
    const sessionIdMatch = window.location.pathname.match(/\/process\/([^\/]+)/);
    if (sessionIdMatch) {
        window.iReDevApp.joinSession(sessionIdMatch[1]);
    }
});

// Global utility functions
window.showNotification = (message, type, duration) => {
    if (window.iReDevApp) {
        window.iReDevApp.showNotification(message, type, duration);
    }
};

window.joinSession = (sessionId) => {
    if (window.iReDevApp) {
        window.iReDevApp.joinSession(sessionId);
    }
};

window.leaveSession = () => {
    if (window.iReDevApp) {
        window.iReDevApp.leaveSession();
    }
};