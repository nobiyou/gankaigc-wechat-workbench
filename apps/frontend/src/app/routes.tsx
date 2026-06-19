import { Navigate, Route, Routes } from "react-router-dom";

import { AppShell } from "./AppShell";
import { DashboardPage } from "../pages/DashboardPage";
import { PipelinePage } from "../pages/PipelinePage";
import { ProjectsPage } from "../pages/ProjectsPage";
import { SettingsPage } from "../pages/SettingsPage";
import { SourcesPage } from "../pages/SourcesPage";
import { WorkbenchPage } from "../pages/WorkbenchPage";

export function AppRoutes() {
  return (
    <Routes>
      <Route element={<AppShell />}>
        <Route index element={<DashboardPage />} />
        <Route path="sources">
          <Route index element={<Navigate to="trends" replace />} />
          <Route path="trends" element={<SourcesPage section="trends" />} />
          <Route path="articles" element={<SourcesPage section="articles" />} />
          <Route path="wechat-import" element={<SourcesPage section="wechat-import" />} />
        </Route>
        <Route path="pipeline">
          <Route index element={<Navigate to="topics" replace />} />
          <Route path="topics" element={<PipelinePage section="topics" />} />
          <Route path="runs" element={<PipelinePage section="runs" />} />
          <Route path="tasks" element={<PipelinePage section="tasks" />} />
        </Route>
        <Route path="projects" element={<ProjectsPage />} />
        <Route path="settings">
          <Route index element={<Navigate to="tone-profiles" replace />} />
          <Route path="tone-profiles" element={<SettingsPage section="tone-profiles" />} />
          <Route path="patterns" element={<SettingsPage section="patterns" />} />
        </Route>
      </Route>

      <Route path="projects/:projectSlug/workbench">
        <Route index element={<Navigate to="topic" replace />} />
        <Route path="topic" element={<WorkbenchPage stage="topic" />} />
        <Route path="outline" element={<WorkbenchPage stage="outline" />} />
        <Route path="draft" element={<WorkbenchPage stage="draft" />} />
        <Route path="assets" element={<WorkbenchPage stage="assets" />} />
        <Route path="publish" element={<WorkbenchPage stage="publish" />} />
        <Route path="*" element={<Navigate to="topic" replace />} />
      </Route>

      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  );
}
