async function renderParent(id) {
  setHeader(
    'Кабинет родителя',
    'Оценки, портфолио, посещаемость и отзывы учителей по разным предметам.'
  );
  showLoading('Загружается родительский режим...');

  try {
    const data = await apiFetch(`${API}/api/parent/${id}/dashboard`);
    const childDashboard = data.child_dashboard || {};
    const subjectRows = Object.entries(childDashboard.subject_summary || {}).map(([subject, avg]) => [
      subject,
      `${Math.round(avg)}%`,
      avg >= 80 ? 'Strong' : avg >= 65 ? 'Stable' : 'Needs support'
    ]);
    const absences = (childDashboard.attendance || []).filter(a => a.status === 'absent').length;

    const gradeRows = (childDashboard.grades || []).map(g => [
      g.subject,
      g.topic,
      `${g.score}/${g.max_score}`,
      g.date
    ]);

    const portfolioHtml = (childDashboard.portfolio || []).map(p => `
      <div class="portfolio-item">
        <div>
          <strong>${p.title}</strong>
          <p>${p.level} • ${p.date}</p>
        </div>
        ${p.verified ? badge('Verified', 'success') : badge('Pending', 'warning')}
      </div>
    `).join('');

    const feedbackHtml = (data.teacher_feedback || []).map(f => `
      <div class="feedback-item">
        <span>${f.subject} • ${f.teacher}</span>
        <strong>Комментарий учителя</strong>
        <p>${f.comment}</p>
      </div>
    `).join('');

    content.innerHTML = `
      <section class="stats-grid">
        ${statCard('Родитель', data.parent.name, 'Observer mode', 'blue')}
        ${statCard('Ребенок', data.child.name, `${data.child.class_name}`, 'green')}
        ${statCard('Пропуски', absences, 'Отмеченные отсутствия', absences ? 'yellow' : 'green')}
        ${statCard('Риск', (childDashboard.ai_report?.risk_level || 'low').toUpperCase(), `Score: ${childDashboard.ai_report?.risk_score ?? 0}`, 'purple')}
      </section>

      <div class="dashboard-grid">
        ${card('Недельная AI-выжимка', `
          <div class="summary-box">
            <h4>Weekly Parent Digest</h4>
            <p>${data.weekly_summary}</p>
          </div>
        `)}

        ${card('Профиль ребенка', `
          <div class="profile-box">
            <div class="profile-avatar">${data.child.name.charAt(0)}</div>
            <div>
              <h4>${data.child.name}</h4>
              <p>Класс: ${data.child.class_name}</p>
              <p>Параллель: ${data.child.grade_level}</p>
            </div>
          </div>
        `)}
      </div>

      ${card('Успеваемость по предметам', table(['Предмет', 'Средний %', 'Статус'], subjectRows))}
      ${card('Последние оценки', table(['Предмет', 'Тема', 'Балл', 'Дата'], gradeRows))}
      ${card('Портфолио ребенка', `<div class="portfolio-grid">${portfolioHtml || '<p>Портфолио пока пустое.</p>'}</div>`)}
      ${card('Отзывы учителей', `<div class="feedback-list">${feedbackHtml || '<p>Комментариев пока нет.</p>'}</div>`)}
    `;
  } catch (err) {
    showError('Ошибка загрузки кабинета родителя', err.message);
  }
}