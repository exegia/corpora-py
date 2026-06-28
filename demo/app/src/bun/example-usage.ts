import { PythonBridge } from "./python-bridge";
const py = new PythonBridge();
const getAuth = async () => {
  await py.init();
  // Calls into the local shared workspace (editable in Docker dev, bundled in prod)
  // After the admin/client/shared refactor, auth lives under the shared package.
  const result = await py.call("shared.auth.main");
  return result;
};

const end = async () => {
  await py.shutdown();
};

export { getAuth, end }
