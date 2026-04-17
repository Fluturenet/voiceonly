(function () {
    'use strict';

    const scanPanel = document.getElementById('scan-panel');
    const stopBtn = document.getElementById('stop-scan');
    const statusDiv = document.getElementById('scan-status');
    const progressBar = document.getElementById('scan-progress-bar');

    if (!scanPanel || !statusDiv || !progressBar) {
        return;
    }

    const scanStatusUrl = scanPanel.dataset.scanStatusUrl;
    const stopScanUrl = scanPanel.dataset.stopScanUrl;

    if (!scanStatusUrl || !stopScanUrl) {
        return;
    }

    async function checkScanStatus() {
        try {
            const response = await fetch(scanStatusUrl);
            const data = await response.json();

            if (data.scanning) {
                statusDiv.textContent = `Scan in corso... (${data.metrics.channels_scanned}/${data.metrics.channels_found} canali scaricati)`;
                if (stopBtn) {
                    stopBtn.classList.remove('d-none');
                }

                if (data.metrics.channels_found > 0) {
                    const percent = (data.metrics.channels_scanned / data.metrics.channels_found) * 100;
                    progressBar.style.width = `${percent}%`;
                }
            } else {
                if (data.metrics.last_run_end) {
                    const ts = new Date(data.metrics.last_run_end).toLocaleString();
                    const duration = Number(data.metrics.last_run_duration || 0).toFixed(0);
                    statusDiv.textContent = `Ultimo scan: ${ts} - Durata: ${duration}s`;
                } else {
                    statusDiv.textContent = 'Nessuno scan in corso';
                }

                if (stopBtn) {
                    stopBtn.classList.add('d-none');
                }
                progressBar.style.width = '0%';
            }
        } catch (error) {
            // Keep UX stable and log details for debugging.
            console.error('Error checking scan status:', error);
        }
    }

    if (stopBtn) {
        stopBtn.addEventListener('click', async function () {
            if (!window.confirm('Fermare lo scan in corso?')) {
                return;
            }

            await fetch(stopScanUrl, { method: 'POST' });
        });
    }

    setInterval(checkScanStatus, 2000);
    checkScanStatus();
})();
