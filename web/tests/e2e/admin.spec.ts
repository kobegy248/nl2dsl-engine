import { test, expect } from '@playwright/test';

test.describe('管理后台', () => {
  test.beforeEach(async ({ page }) => {
    await page.goto('/admin');
  });

  test('管理后台页面渲染', async ({ page }) => {
    await expect(page.getByText('指标管理')).toBeVisible();
    await expect(page.getByText('审计日志')).toBeVisible();
    await expect(page.getByText('权限配置')).toBeVisible();
  });

  test('指标管理展示指标表格', async ({ page }) => {
    await page.getByText('指标管理').click();
    await page.waitForTimeout(2000);

    await expect(page.getByText('指标定义')).toBeVisible();
    await expect(page.getByText('维度定义')).toBeVisible();
    await expect(page.getByText('数据源')).toBeVisible();
  });

  test('审计日志页面展示列表', async ({ page }) => {
    await page.getByText('审计日志').click();
    await page.waitForTimeout(2000);

    // 检查表格列头
    await expect(page.getByText('时间')).toBeVisible();
    await expect(page.getByText('用户')).toBeVisible();
    await expect(page.getByText('问题')).toBeVisible();
    await expect(page.getByText('状态')).toBeVisible();
  });

  test('权限配置页面渲染', async ({ page }) => {
    await page.getByText('权限配置').click();
    await page.waitForTimeout(500);

    await expect(page.getByText('权限配置')).toBeVisible();
  });

  test('侧边栏可切换到查询工作台', async ({ page }) => {
    await page.getByText('查询工作台').click();
    await expect(page.locator('textarea')).toBeVisible();
  });
});
