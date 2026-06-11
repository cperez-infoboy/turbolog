<div class="spinner-container">
	<div class="spinner-ring"></div>
</div>

<style>
	.spinner-container {
		display: flex;
		align-items: center;
		justify-content: center;
		padding: 2rem;
	}

	.spinner-ring {
		width: 40px;
		height: 40px;
		border: 3px solid transparent;
		border-top-color: var(--neon-cyan);
		border-right-color: var(--neon-cyan);
		border-radius: 50%;
		animation: spin 0.8s linear infinite;
		box-shadow:
		0 0 10px rgba(0, 255, 255, 0.3),
		0 0 20px rgba(0, 255, 255, 0.1);
	}

	@keyframes spin {
		to {
			transform: rotate(360deg);
		}
	}
</style>
