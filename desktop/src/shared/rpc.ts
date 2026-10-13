import type { RPCSchema } from "electrobun/main";

export interface SidecarStatus {
	readonly state: "starting" | "ready" | "failed" | "stopped";
	readonly url: string | null;
	readonly error: string | null;
	readonly authRequired: boolean | null;
}

export type DesktopRPC = {
	bun: RPCSchema<{
		requests: {
			getSidecarStatus: { params: {}; response: SidecarStatus };
		};
		messages: {};
	}>;
	webview: RPCSchema<{ requests: {}; messages: {} }>;
};
