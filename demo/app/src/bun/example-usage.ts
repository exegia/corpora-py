import { PythonBridge } from "./python-bridge";
const py = new PythonBridge();
const getAuth = async () => {
  await py.init();
  // Calls into the local exegia library (editable in Docker dev, bundled in prod)
  const result = await py.call("exegia.auth.main");
  return result;
};

const end = async () => {
  await py.shutdown();
};

export { getAuth, end }
