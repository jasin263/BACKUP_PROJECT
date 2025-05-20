
document.addEventListener('DOMContentLoaded', function() {
    // Auto-refresh the dashboard every 60 seconds
    setTimeout(function() {
        window.location.reload();
    }, 60000);
    
    // Initialize any tooltips
    const tooltipTriggerList = [].slice.call(document.querySelectorAll('[data-bs-toggle="tooltip"]'));
    tooltipTriggerList.map(function (tooltipTriggerEl) {
        return new bootstrap.Tooltip(tooltipTriggerEl);
    });
});
