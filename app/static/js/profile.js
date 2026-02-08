window.logout = async () => {
    try {
        await fetch('/api/auth/logout', { method: 'POST', credentials: 'include' });
    } catch (error) {
        console.error('Logout error:', error);
    } finally {
        localStorage.clear();
        sessionStorage.clear();
        window.location.href = '/';
    }
};

document.addEventListener('DOMContentLoaded', function() {
    // Get DOM elements
    const profileView = document.getElementById('profile-view');
    const profileEdit = document.getElementById('profile-edit');
    const editButton = document.getElementById('edit-profile-button');
    const cancelButton = document.getElementById('cancel-edit-button');
    
    // Store user data globally for edit form population
    let currentUserData = null;
    const renderAvatar = (user, targetId) => {
        const container = document.getElementById(targetId);
        if (!container) {
            return;
        }

        const iconPath = (user && user.avatar_icon_path) ? user.avatar_icon_path : null;
        const color = (user && user.avatar_color) ? user.avatar_color : '#6B7280';
        const label = (user && (user.first_name || user.login)) ? (user.first_name || user.login) : 'User';

        if (iconPath) {
            container.innerHTML = `
                <div style="width:72px;height:72px;border-radius:50%;background:${color};display:flex;align-items:center;justify-content:center;overflow:hidden;">
                    <img src="${iconPath}" alt="Avatar for ${label}" style="width:56px;height:56px;display:block;">
                </div>
            `;
            return;
        }

        const fallbackText = String(label).slice(0, 1).toUpperCase();
        container.innerHTML = `
            <div style="width:72px;height:72px;border-radius:50%;background:${color};display:flex;align-items:center;justify-content:center;color:#fff;font-size:1.75rem;font-weight:700;">
                ${fallbackText}
            </div>
        `;
    };

    fetch('/api/users/me/profile', {
        credentials: 'include'
    })
    .then(response => {
        if (!response.ok) {
            throw new Error(`HTTP error! status: ${response.status}`);
        }
        return response.json();
    })
    .then(user => {
        currentUserData = user;
        console.log('User data:', user); // Log the user data
        
        // Populate profile data
        const displayName = user.first_name || user.login;
        document.getElementById('profile-display-name').textContent = displayName || 'Not set';
        document.getElementById('profile-email').textContent = user.email || 'Not set';
        document.getElementById('profile-first-name').textContent = user.first_name || 'Not set';
        document.getElementById('profile-last-name').textContent = user.last_name || 'Not set';
        document.getElementById('profile-organization').textContent = user.organization || 'Not set';
        document.getElementById('profile-about-me').textContent = user.about_me || 'Not set';
        renderAvatar(user, 'profile-svg-container');
        renderAvatar(user, 'edit-avatar-preview');
    })
    .catch(error => {
        console.error('Error fetching profile:', error);
        document.getElementById('profile-message').textContent =
            'Failed to load profile data. Please try again later.';
    });

    // Edit button click handler
    editButton.addEventListener('click', () => {
        // Switch to edit view
        profileView.style.display = 'none';
        profileEdit.style.display = 'block';
        
        // Populate edit form with current data
        if (currentUserData) {
            document.getElementById('edit-display-name').value = currentUserData.first_name || '';
            document.getElementById('edit-about-me').value = currentUserData.about_me || '';
            document.getElementById('edit-organization').value = currentUserData.organization || '';
            renderAvatar(currentUserData, 'edit-avatar-preview');
        }
    });

    // Cancel button click handler
    cancelButton.addEventListener('click', () => {
        // Switch back to view mode
        profileEdit.style.display = 'none';
        profileView.style.display = 'block';
        
        // Clear any messages
        document.getElementById('profile-message').textContent = '';
    });

    // Get form and message elements
    const profileForm = document.getElementById('profile-form');
    const profileMessage = document.getElementById('profile-message');
    const passwordForm = document.getElementById('password-form');
    const passwordMessage = document.getElementById('password-message');

    // Form submission handler
    profileForm.addEventListener('submit', async (event) => {
        event.preventDefault();
        
        // Create request body from form data
        const requestBody = {
            first_name: document.getElementById('edit-display-name').value.trim() || null,
            about_me: document.getElementById('edit-about-me').value.trim(),
            organization: document.getElementById('edit-organization').value.trim() || null,
        };

        try {
            const response = await fetch('/api/users/me/profile', {
                method: 'PATCH',
                headers: {
                    'Content-Type': 'application/json'
                },
                credentials: 'include',
                body: JSON.stringify(requestBody)
            });

            if (response.ok) {
                const updatedUser = await response.json();
                currentUserData = updatedUser;
                
                // Update view with new data
                document.getElementById('profile-display-name').textContent =
                    updatedUser.first_name || updatedUser.login || 'Not set';
                document.getElementById('profile-first-name').textContent = updatedUser.first_name || 'Not set';
                document.getElementById('profile-last-name').textContent = updatedUser.last_name || 'Not set';
                document.getElementById('profile-about-me').textContent = updatedUser.about_me || 'Not set';
                document.getElementById('profile-organization').textContent = updatedUser.organization || 'Not set';
                renderAvatar(updatedUser, 'profile-svg-container');
                renderAvatar(updatedUser, 'edit-avatar-preview');
                
                // Switch back to view mode
                profileEdit.style.display = 'none';
                profileView.style.display = 'block';
                
                // Show success message
                profileMessage.textContent = 'Profile updated successfully!';
                profileMessage.style.color = 'green';
            } else {
                const errorData = await response.json().catch(() => ({}));
                profileMessage.textContent = errorData.detail || 'Failed to update profile. Please try again.';
                profileMessage.style.color = 'red';
            }
        } catch (error) {
            console.error('Error updating profile:', error);
            profileMessage.textContent = 'Network error. Please try again.';
            profileMessage.style.color = 'red';
        }
    });

    if (passwordForm) {
        passwordForm.addEventListener('submit', async (event) => {
            event.preventDefault();
            if (passwordMessage) {
                passwordMessage.textContent = '';
            }

            const currentPassword = document.getElementById('current-password').value;
            const newPassword = document.getElementById('new-password').value;
            const confirmPassword = document.getElementById('confirm-password').value;

            if (!currentPassword || !newPassword || !confirmPassword) {
                if (passwordMessage) {
                    passwordMessage.textContent = 'Please fill out all password fields.';
                    passwordMessage.style.color = 'red';
                }
                return;
            }

            if (newPassword !== confirmPassword) {
                if (passwordMessage) {
                    passwordMessage.textContent = 'New password and confirmation do not match.';
                    passwordMessage.style.color = 'red';
                }
                return;
            }

            try {
                const response = await fetch('/api/users/me/change_password', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    credentials: 'include',
                    body: JSON.stringify({
                        current_password: currentPassword,
                        new_password: newPassword
                    })
                });

                if (response.ok) {
                    document.getElementById('current-password').value = '';
                    document.getElementById('new-password').value = '';
                    document.getElementById('confirm-password').value = '';
                    if (passwordMessage) {
                        passwordMessage.textContent = 'Password updated successfully.';
                        passwordMessage.style.color = 'green';
                    }
                } else {
                    const errorData = await response.json().catch(() => ({}));
                    if (passwordMessage) {
                        passwordMessage.textContent = errorData.detail || 'Failed to update password.';
                        passwordMessage.style.color = 'red';
                    }
                }
            } catch (error) {
                console.error('Error updating password:', error);
                if (passwordMessage) {
                    passwordMessage.textContent = 'Network error. Please try again.';
                    passwordMessage.style.color = 'red';
                }
            }
        });
    }

    const generateAvatarButton = document.getElementById('generate-avatar-button');
    if (generateAvatarButton) {
        generateAvatarButton.addEventListener('click', async () => {
            if (generateAvatarButton.disabled) {
                return;
            }

            generateAvatarButton.disabled = true;
            generateAvatarButton.textContent = 'Generating...';
            try {
                const response = await fetch('/api/users/me/avatar/regenerate', {
                    method: 'POST',
                    credentials: 'include'
                });
                if (!response.ok) {
                    const errorData = await response.json().catch(() => ({}));
                    throw new Error(errorData.detail || 'Failed to regenerate avatar.');
                }
                const updatedUser = await response.json();
                currentUserData = updatedUser;
                renderAvatar(updatedUser, 'profile-svg-container');
                renderAvatar(updatedUser, 'edit-avatar-preview');
            } catch (error) {
                console.error('Error regenerating avatar:', error);
                profileMessage.textContent = String(error.message || 'Could not generate avatar.');
                profileMessage.style.color = 'red';
            } finally {
                generateAvatarButton.disabled = false;
                generateAvatarButton.textContent = 'Generate new avatar';
            }
        });
    }

    const generateAvatarColorButton = document.getElementById('generate-avatar-color-button');
    if (generateAvatarColorButton) {
        generateAvatarColorButton.addEventListener('click', async () => {
            if (generateAvatarColorButton.disabled) {
                return;
            }

            generateAvatarColorButton.disabled = true;
            generateAvatarColorButton.textContent = 'Generating...';
            try {
                const response = await fetch('/api/users/me/avatar/regenerate_color', {
                    method: 'POST',
                    credentials: 'include'
                });
                if (!response.ok) {
                    const errorData = await response.json().catch(() => ({}));
                    throw new Error(errorData.detail || 'Failed to regenerate avatar color.');
                }
                const updatedUser = await response.json();
                currentUserData = updatedUser;
                renderAvatar(updatedUser, 'profile-svg-container');
                renderAvatar(updatedUser, 'edit-avatar-preview');
            } catch (error) {
                console.error('Error regenerating avatar color:', error);
                profileMessage.textContent = String(error.message || 'Could not generate avatar color.');
                profileMessage.style.color = 'red';
            } finally {
                generateAvatarColorButton.disabled = false;
                generateAvatarColorButton.textContent = 'Generate new color';
            }
        });
    }
});
