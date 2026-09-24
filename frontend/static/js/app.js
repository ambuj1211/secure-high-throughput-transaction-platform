(function () {
    const refreshButton =
        document.getElementById("refresh-dashboard");

    if (!refreshButton) {
        return;
    }

    const setText = (id, value) => {
        const element = document.getElementById(id);

        if (element) {
            element.textContent = value;
        }
    };

    const number = (value) => {
        if (value === null || value === undefined) {
            return "—";
        }

        return Number(value).toLocaleString(
            undefined,
            {
                maximumFractionDigits: 2,
            },
        );
    };

    const milliseconds = (value) => {
        if (value === null || value === undefined) {
            return "—";
        }

        return `${Math.round(Number(value) * 1000)} ms`;
    };

    refreshButton.addEventListener(
        "click",
        async () => {
            const originalText =
                refreshButton.textContent;

            refreshButton.disabled = true;
            refreshButton.textContent =
                "Refreshing…";

            try {
                const response = await fetch(
                    "/dashboard/refresh",
                    {
                        headers: {
                            "Accept":
                                "application/json",
                        },
                    },
                );

                if (!response.ok) {
                    throw new Error(
                        `HTTP ${response.status}`,
                    );
                }

                const data =
                    await response.json();

                const metrics =
                    data.metrics || {};

                setText(
                    "request-rate",
                    number(
                        metrics.request_rate,
                    ),
                );

                setText(
                    "transaction-rate",
                    number(
                        metrics.transaction_rate,
                    ),
                );

                setText(
                    "error-rate",
                    number(
                        metrics.error_rate,
                    ),
                );

                setText(
                    "transaction-p95",
                    milliseconds(
                        metrics.transaction_p95,
                    ),
                );

            } catch (error) {
                console.error(
                    "Dashboard refresh failed:",
                    error,
                );
            } finally {
                refreshButton.disabled =
                    false;

                refreshButton.textContent =
                    originalText;
            }
        },
    );
})();
