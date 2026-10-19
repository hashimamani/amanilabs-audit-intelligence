import { Component, type ErrorInfo, type ReactNode } from "react";

interface Props {
  children: ReactNode;
}
interface State {
  error: Error | null;
}

export class ErrorBoundary extends Component<Props, State> {
  state: State = { error: null };

  static getDerivedStateFromError(error: Error): State {
    return { error };
  }

  componentDidCatch(error: Error, info: ErrorInfo): void {
    console.error("Unhandled error in the UI", error, info.componentStack);
  }

  render() {
    if (this.state.error) {
      return (
        <div className="mx-auto mt-24 max-w-md rounded-lg border border-red-200 bg-red-50 p-6 text-sm text-red-800">
          <h1 className="text-base font-semibold">Something went wrong</h1>
          <p className="mt-2">{this.state.error.message}</p>
          <button onClick={() => window.location.reload()} className="btn-secondary mt-4">
            Reload
          </button>
        </div>
      );
    }
    return this.props.children;
  }
}
