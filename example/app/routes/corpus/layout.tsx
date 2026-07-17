import { Link, Outlet, useLocation, useNavigate, useParams } from "react-router"
import { Badge } from "~/components/ui/badge"
import {
  Breadcrumb,
  BreadcrumbItem,
  BreadcrumbLink,
  BreadcrumbList,
  BreadcrumbPage,
  BreadcrumbSeparator,
} from "~/components/ui/breadcrumb"
import { cn } from "~/lib/utils"

/**
 * Shared chrome (breadcrumb + display header + Detail/View tabs) for a single
 * corpus. `:id` is the archive filename minus `.corpus`, which already reads as
 * the corpus display name, so it's used directly here rather than fetching the
 * manifest a second time — the detail tab owns that request.
 */
export default function CorpusLayout() {
  const { id } = useParams()
  const { pathname } = useLocation()
  const navigate = useNavigate()
  const activeTab = pathname.endsWith("/view") ? "view" : "detail"
  const displayName = id ?? "Corpus"
  // `id` comes back decoded from useParams, so re-encode when building URLs.
  const encodedId = encodeURIComponent(id ?? "")

  return (
    <div className="flex w-full flex-col gap-6">
      <Breadcrumb>
        <BreadcrumbList>
          <BreadcrumbItem>
            <BreadcrumbLink render={<Link to="/explore" />}>
              Explore
            </BreadcrumbLink>
          </BreadcrumbItem>
          <BreadcrumbSeparator />
          <BreadcrumbItem>
            <BreadcrumbPage className="max-w-[24rem] truncate">
              {displayName}
            </BreadcrumbPage>
          </BreadcrumbItem>
        </BreadcrumbList>
      </Breadcrumb>

      <div className="flex items-center gap-3">
        <h2 className="truncate text-2xl font-semibold" title={displayName}>
          {displayName}
        </h2>
        <Badge variant="secondary">corpus</Badge>
      </div>

      <div
        className="flex items-center gap-2 border-b"
        role="tablist"
        aria-label="Corpus sections"
      >
        <button
          type="button"
          role="tab"
          aria-selected={activeTab === "detail"}
          onClick={() => navigate(`/corpus/${encodedId}`)}
          data-cuelume-press
          data-cuelume-release
          className={cn(
            "-mb-px cursor-pointer border-b-2 px-2 py-1 text-sm transition-colors",
            activeTab === "detail"
              ? "border-neutral-900 font-medium dark:border-neutral-100"
              : "border-transparent text-neutral-500 hover:text-foreground dark:text-neutral-400"
          )}
        >
          Detail
        </button>
        <button
          type="button"
          role="tab"
          aria-selected={activeTab === "view"}
          onClick={() => navigate(`/corpus/${encodedId}/view`)}
          data-cuelume-press
          data-cuelume-release
          className={cn(
            "-mb-px cursor-pointer border-b-2 px-2 py-1 text-sm transition-colors",
            activeTab === "view"
              ? "border-neutral-900 font-medium dark:border-neutral-100"
              : "border-transparent text-neutral-500 hover:text-foreground dark:text-neutral-400"
          )}
        >
          View
        </button>
      </div>

      <Outlet />
    </div>
  )
}
