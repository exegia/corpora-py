import {
  index,
  prefix,
  route,
  type RouteConfig,
} from "@react-router/dev/routes"

export default [
  index("routes/home.tsx"),

  // explore — browse/search the .corpus archives published to the Hub
  route("explore", "routes/explore.tsx"),

  ...prefix("corpus", [
    // corpus/upload — ingest a new corpus
    route("upload", "routes/corpus/upload.tsx"),
    // corpus/convert — convert a source (EPUB/HTML) into a Text-Fabric dataset
    route("convert", "routes/corpus/convert.tsx"),

    // corpus/:id — shared layout (header + tabs) for a single corpus.
    //   index -> corpus/:id (detail)
    //   view -> corpus/:id/view (reader)
    route(":id", "routes/corpus/layout.tsx", [
      index("routes/corpus/detail.tsx"),
      route("view", "routes/corpus/view.tsx"),
    ]),
  ]),
  // route("logs", "routes/logs.tsx")
] satisfies RouteConfig
